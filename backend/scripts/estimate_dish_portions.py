"""Ước lượng khối lượng một suất cho các món đang lưu dinh dưỡng theo suất (serving_unit PORTION).

Bảng món ăn của Viện Dinh dưỡng (viendinhduong.vn, mã HAN/HAP/SFF/VPF) chỉ công bố dinh dưỡng cho "1 suất",
không công bố khối lượng suất (đã kiểm tra 1024/1024 món qua API của trang, 10/11/2026). Để mọi món tính theo
100 g/100 ml, script này hỏi model khối lượng điển hình của một suất rồi để code kiểm tra:

* khối lượng protein + carbohydrate + chất béo + xơ của suất không được vượt khối lượng suất;
* mật độ năng lượng phải nằm trong khoảng vật lý (không quá 900 kcal/100 g, không quá thấp với món có năng lượng);
* khối lượng trong khoảng 5–1500.

Món bị loại thì hỏi lại một lần kèm lý do; vẫn sai thì dùng khối lượng mặc định theo nhóm món (nâng lên đủ chứa
macro).

Món có bản ghi cùng tên tính theo 100 g (ví dụ "Xoài") thì khối lượng suất suy ra được từ dữ liệu: kcal của suất chia
kcal trên 100 g, khi tỉ lệ theo protein/carbohydrate cũng khớp (lệch dưới 30 %). Những món này dùng khối lượng suy ra
(derived_from_food_100g), và ước lượng của model cho chúng chỉ để đo sai số của model (in ra cuối lần chạy).
Kết quả được migration 0032 ghi vào data_quality.portion_estimate kèm phương pháp.

    python -m scripts.estimate_dish_portions --limit 40 --out /tmp/pilot.json     # chạy thử
    python -m scripts.estimate_dish_portions                                      # toàn bộ, ghi alembic/data
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

import psycopg
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agentic.core.app.config import agent_settings
from agentic.core.llm import Models
from core.database import get_postgres_connection_string
from domains.shared.models.catalog import normalize_food_text

logger = logging.getLogger("estimate_dish_portions")
OUT = Path(__file__).resolve().parents[1] / "alembic" / "data" / "dish_portions.json"
BATCH = 20
CONCURRENCY = 4
MIN_WEIGHT, MAX_WEIGHT = 5, 1500

# Khối lượng mặc định theo từ khoá trong tên rồi theo nhóm; chỉ dùng khi model không cho kết quả hợp lệ.
KEYWORD_DEFAULTS = (
    (("phở", "bún", "miến", "hủ tiếu", "bánh canh", "mì", "mỳ", "lẩu", "súp", "cháo", "bánh đa"), 500, "G", "1 tô"),
    (("cơm",), 350, "G", "1 đĩa"),
    (("xôi",), 200, "G", "1 gói"),
    (("chè",), 250, "G", "1 cốc"),
    (("nước", "sinh tố", "trà", "cà phê", "sữa", "bia"), 300, "ML", "1 cốc"),
    (("bánh",), 100, "G", "1 cái"),
)
DEFAULT = (200, "G", "1 suất")
# Đơn vị do code quyết định theo tên (model gán ML không nhất quán: canh, kem, sữa chua ăn bằng thìa).
BEVERAGES = ("nuoc ", "tra ", "ca phe", "sinh to", "bia", "ruou", "ca cao", "cacao", "milo", "soda", "sua chua uong")


def unit_for(name: str) -> str:
    """ML cho đồ uống (1 g ≈ 1 ml), G cho mọi món ăn khác kể cả chè, kem, canh."""
    key = normalize_food_text(name) + " "
    if key.startswith(BEVERAGES) or (key.startswith("sua ") and not key.startswith(("sua chua ", "sua bot", "sua dac"))):
        return "ML"
    return "G"

SYSTEM = """Bạn là chuyên gia dinh dưỡng Việt Nam. Mỗi dòng là một món trong bảng thành phần món ăn của Viện Dinh dưỡng,
với năng lượng và macro của ĐÚNG MỘT SUẤT (khối lượng suất không được công bố).
Với từng món, ước lượng khối lượng điển hình của một suất như được bán/phục vụ ở Việt Nam, sao cho khớp với năng lượng
và macro đã cho (đây là căn cứ chính: ví dụ 1 tô phở ~450–600 g, 1 đĩa cơm ~350–500 g, 1 cái bánh bao ~120–150 g).
- unit: "ML" cho đồ uống (nước ép, sinh tố, trà, cà phê, sữa, bia, nước giải khát, chè dạng nước uống bằng cốc);
  "G" cho mọi món ăn khác (kể cả kem, caramen, chè đặc ăn bằng thìa). Với ML coi 1 g ≈ 1 ml.
- weight: số gam (hoặc ml) của một suất; tổng protein + carbohydrate + chất béo phải nhỏ hơn khối lượng.
- label: đơn vị gia dụng tiếng Việt của một suất, ví dụ "1 tô", "1 bát", "1 đĩa", "1 cái", "1 cốc", "1 ly", "1 quả", "1 suất".
Trả về đúng một kết quả cho mỗi id được hỏi."""


class Portion(BaseModel):
    id: str = Field(description="The id of the dish exactly as given")
    weight: float = Field(gt=0, description="Grams (or millilitres when unit is ML) of one serving")
    unit: str = Field(description="G or ML")
    label: str = Field(max_length=40, description="Vietnamese household measure of one serving, e.g. 1 tô")


class Portions(BaseModel):
    """Serving weights of the listed dishes, one entry per dish id."""
    items: list[Portion]


def _num(value) -> float:
    return float(value) if value is not None else 0.0


def check(dish: dict, weight: float, unit: str) -> str | None:
    """Lý do loại khối lượng này cho món, hoặc None khi hợp lệ."""
    if unit not in ("G", "ML"):
        return f"unit {unit!r} không phải G/ML"
    if not MIN_WEIGHT <= weight <= MAX_WEIGHT:
        return f"khối lượng {weight:g} ngoài khoảng {MIN_WEIGHT}–{MAX_WEIGHT}"
    macros = sum(_num(dish[field]) for field in ("protein_g", "carbohydrate_g", "fat_g", "fiber_g"))
    if macros > weight:
        return f"macro {macros:g} g lớn hơn khối lượng {weight:g}"
    kcal = _num(dish["energy_kcal"])
    density = kcal * 100 / weight
    if density > 900:
        return f"mật độ {density:.0f} kcal/100 vượt 900"
    if kcal >= 50 and density < 10:
        return f"mật độ {density:.1f} kcal/100 quá thấp"
    return None


def fallback(dish: dict) -> tuple[float, str, str]:
    name = (dish["name_vi"] or "").lower()
    weight, unit, label = next(((w, u, lbl) for words, w, u, lbl in KEYWORD_DEFAULTS
                                if any(word in name for word in words)), DEFAULT)
    macros = sum(_num(dish[field]) for field in ("protein_g", "carbohydrate_g", "fat_g", "fiber_g"))
    kcal = _num(dish["energy_kcal"])
    # Nâng khối lượng để chứa đủ macro và không vượt 600 kcal/100 g.
    return max(weight, round(macros * 1.25), round(kcal / 6)), unit, label


def _line(dish: dict) -> str:
    def fmt(field):
        return "?" if dish[field] is None else f"{float(dish[field]):g}"
    return (f"id={dish['id']} | {dish['name_vi']} ({dish['name_en'] or '-'}) | nhóm: {dish['category_vi'] or '-'} | "
            f"{fmt('energy_kcal')} kcal, P {fmt('protein_g')} g, C {fmt('carbohydrate_g')} g, "
            f"F {fmt('fat_g')} g, xơ {fmt('fiber_g')} g")


async def estimate_batch(model, batch: list[dict], semaphore: asyncio.Semaphore) -> dict[str, dict]:
    pending = {dish["id"]: dish for dish in batch}
    results: dict[str, dict] = {}
    messages = [SystemMessage(content=SYSTEM),
                HumanMessage(content="\n".join(_line(dish) for dish in batch))]
    for attempt in range(2):
        try:
            async with semaphore:
                answer = await model.ainvoke(messages)
            items = (answer.items if isinstance(answer, Portions) else Portions.model_validate(answer).items) if answer else []
        except Exception as exc:  # lỗi mạng/định dạng: lần sau hoặc dùng mặc định
            logger.warning("batch failed attempt=%s error=%s", attempt + 1, type(exc).__name__)
            items = []
        problems = []
        for item in items:
            dish = pending.get(item.id)
            if dish is None:
                continue
            unit = item.unit.strip().upper()
            problem = check(dish, item.weight, unit)
            if problem:
                problems.append(f"id={item.id}: {problem}")
                continue
            results[item.id] = {"weight": round(item.weight, 1), "unit": unit, "label": item.label.strip(),
                                "method": "llm_estimate"}
            del pending[item.id]
        if not pending:
            break
        missing = [f"id={key}: thiếu kết quả" for key in pending if all(key not in p for p in problems)]
        messages = [SystemMessage(content=SYSTEM),
                    HumanMessage(content="\n".join(_line(dish) for dish in pending.values())
                                 + "\n\nLần trước bị từ chối:\n" + "\n".join(problems + missing))]
    for key, dish in pending.items():
        weight, unit, label = fallback(dish)
        results[key] = {"weight": float(weight), "unit": unit, "label": label, "method": "category_default"}
    return results


TWINS = """select d.id::text, f.energy_kcal, f.protein_g, f.carbohydrate_g
from foods d join foods f on f.normalized_name_vi = d.normalized_name_vi
 and f.serving_unit = 'G' and f.serving_size = 100 and f.energy_kcal > 0
where d.serving_unit = 'PORTION' and d.energy_kcal > 0"""


def load(limit: int | None) -> tuple[list[dict], dict[str, list[tuple]]]:
    query = ("select id::text, code, name_vi, name_en, category_vi, energy_kcal, protein_g, carbohydrate_g, fat_g, "
             "fiber_g from foods where serving_unit = 'PORTION' order by is_active desc, id")
    twins: dict[str, list[tuple]] = {}
    with psycopg.connect(get_postgres_connection_string()) as conn, conn.cursor() as cur:
        cur.execute(query + (f" limit {int(limit)}" if limit else ""))
        names = [column.name for column in cur.description]
        dishes = [dict(zip(names, row)) for row in cur.fetchall()]
        cur.execute(TWINS)
        for dish_id, *values in cur.fetchall():
            twins.setdefault(dish_id, []).append(tuple(values))
    return dishes, twins


def derived(dish: dict, twins: list[tuple]) -> float | None:
    """Khối lượng suất suy ra từ bản ghi cùng tên theo 100 g, khi tỉ lệ kcal và macro thống nhất."""
    for kcal, protein, carbs in twins:
        implied = _num(dish["energy_kcal"]) / float(kcal) * 100
        checks = [_num(dish[field]) / float(per100) * 100
                  for field, per100 in (("protein_g", protein), ("carbohydrate_g", carbs))
                  if dish[field] and per100 and float(per100) >= 1]
        if checks and all(abs(value - implied) <= 0.3 * implied for value in checks) \
                and check(dish, implied, "G") is None:
            return round(implied, 1)
    return None


async def main(limit: int | None, out: Path) -> None:
    dishes, twins = load(limit)
    settings = agent_settings
    model = Models(settings).get("summary").with_structured_output(Portions)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    batches = [dishes[start:start + BATCH] for start in range(0, len(dishes), BATCH)]
    merged: dict[str, dict] = {}
    for result in await asyncio.gather(*(estimate_batch(model, batch, semaphore) for batch in batches)):
        merged.update(result)
    rows, errors = {}, []
    for dish in dishes:
        row = {"code": dish["code"], "name_vi": dish["name_vi"], **merged[dish["id"]]}
        weight = derived(dish, twins.get(dish["id"], []))
        if weight is not None:
            if row["method"] == "llm_estimate":
                errors.append((dish["name_vi"], weight, row["weight"]))
            row.update(weight=weight, method="derived_from_food_100g", llm_weight=row["weight"])
        row["unit"] = unit_for(dish["name_vi"])
        rows[dish["id"]] = row
    relative = sorted(abs(llm - truth) / truth for _name, truth, llm in errors)
    evaluation = {"dishes": len(relative),
                  "median_abs_error": round(relative[len(relative) // 2], 3) if relative else None,
                  "within_25pct": round(sum(value <= 0.25 for value in relative) / len(relative), 3) if relative else None}
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": settings.DEFAULT_MODEL, "source_note": "per-serving values from viendinhduong.vn dish tables; "
               "serving weight not published: derived from a same-name per-100 g record when consistent, otherwise "
               "estimated by model and checked in code", "model_vs_derived": evaluation, "dishes": rows}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    methods = {}
    for row in rows.values():
        methods[row["method"]] = methods.get(row["method"], 0) + 1
    print(f"{len(rows)} dishes -> {out} {methods}")
    print(f"model vs derived: {evaluation}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.out))
