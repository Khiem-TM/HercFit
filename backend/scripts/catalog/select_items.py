"""Bước 3: gắn nhãn và chọn ~500 mục cho catalog v2.

``annotate`` hỏi LLM (deepseek/deepseek-v4-flash qua OpenRouter) cho từng nguồn:

* độ phổ biến 1–5 trong bữa ăn hằng ngày của người Việt và cờ ``keep``;
* tên tiếng Việt tự nhiên, tên tiếng Anh, tối đa 5 alias, một category trong bộ cố định;
* nhãn khẩu phần gia dụng ("1 tô"); với thực phẩm đếm được thêm khối lượng điển hình ("1 quả trứng" ≈ 50 g).

Kết quả lưu ở ``.cache/catalog/annotations_<kind>.json``. ``build`` ghép nhãn với số liệu nguồn và khối lượng đọc
từ infographic (bước 2, ``candidates.py``), gộp mỗi tên một bản, xếp hạng theo độ phổ biến trong hạn mức từng loại
rồi ghi ``selection.csv`` (mọi ứng viên, cột include = 1 cho mục được chọn) để người duyệt và sửa tay.

    python -m scripts.catalog.select_items annotate --kind dish --limit 20
    python -m scripts.catalog.select_items annotate --kind food
    python -m scripts.catalog.select_items annotate --kind product
    python -m scripts.catalog.select_items build [--force]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import unicodedata

from pydantic import BaseModel, Field, ValidationError

from scripts.catalog.common import CACHE, HERE, chat_json, model_client, read_json, write_json

MODEL = "deepseek/deepseek-v4-flash"
BATCH = 30
CONCURRENCY = 4

DISH_CATEGORIES = (
    "Phở, bún, miến, mì", "Cơm, xôi", "Cháo, súp", "Bánh mì, bánh mặn", "Món mặn (thịt, cá, trứng)", "Rau, canh",
    "Chè, tráng miệng, bánh ngọt", "Đồ uống", "Trái cây", "Đồ ăn nhanh",
)
FOOD_CATEGORIES = (
    "Ngũ cốc, khoai củ", "Thịt, cá, trứng, hải sản", "Rau, củ, nấm", "Trái cây", "Sữa, chế phẩm sữa", "Đậu, hạt",
    "Gia vị, nước chấm", "Dầu, mỡ, bơ", "Bánh kẹo, đồ ăn vặt", "Đồ uống",
)
PRODUCT_CATEGORY = "Sản phẩm đóng gói"
CATEGORIES = tuple(dict.fromkeys(DISH_CATEGORIES + FOOD_CATEGORIES + (PRODUCT_CATEGORY,)))

# Tên món không dùng: giá tiền, số cái trong tên (dinh dưỡng tính theo 100 g), cơm suất/bình dân theo giá.
NOISY_NAME = re.compile(r"\d+\s*k\b|\(\s*\d+\s*(cái|viên|miếng|xiên|chiếc|quả|con)|suất|bình dân|văn phòng", re.I)


def accented(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class Annotation(BaseModel):
    id: str = Field(coerce_numbers_to_str=True)  # mã số của bảng thực phẩm (10001) hay được trả về dạng số
    keep: bool
    popularity: int = Field(ge=1, le=5)
    name_vi: str = Field(min_length=2, max_length=80)
    name_en: str = Field(min_length=2, max_length=120)
    category: str
    aliases: list[str] = Field(default_factory=list, max_length=5)
    portion_label: str | None = Field(default=None, max_length=30)
    portion_grams: float | None = Field(default=None, gt=0, le=2000)


COMMON = """Bạn là chuyên gia dinh dưỡng và ẩm thực Việt Nam, đang làm sạch catalog thực phẩm cho app ghi bữa ăn.
Với MỖI dòng (theo id), trả về một object:
- id: đúng id đã cho.
- keep: false nếu không nên có trong catalog app (xem tiêu chí riêng bên dưới), ngược lại true.
- popularity: 1–5, mức người Việt hay ăn/uống và hay muốn ghi lại (5 = rất phổ biến hằng ngày như cơm trắng, phở bò,
  trứng luộc; 3 = khá quen; 1 = hiếm, đặc sản địa phương ít gặp).
- name_vi: tên tiếng Việt tự nhiên như người dùng gõ, viết hoa chữ đầu, không dấu phẩy kiểu bảng tra, không số cái,
  không giá tiền, không tên quán/tên người. Giữ chi tiết làm món khác nhau về dinh dưỡng (luộc/rán, sống/chín, có đường).
- name_en: tên tiếng Anh ngắn, đúng nghĩa.
- category: đúng một giá trị trong danh sách: {categories}.
- aliases: 0–5 tên gọi khác người dùng hay gõ (tên vùng miền, cách gọi ngắn, tên gốc trong bảng nếu khác name_vi);
  không lặp name_vi, không thêm alias chung chung trùng món khác (ví dụ không dùng "phở" làm alias của "Phở bò tái").
{extra}
Trả về DUY NHẤT một JSON array các object, không giải thích."""

DISH_EXTRA = """- portion_label: đơn vị gia dụng của một suất món này ("1 tô", "1 bát", "1 đĩa", "1 cái", "1 cốc", "1 ly", "1 phần").
- keep=false khi: tên chứa tên quán/tên người, món ghép nhiều món (combo), là trái cây/thực phẩm sống chứ không phải món
  (sẽ lấy từ bảng thực phẩm), hoặc món quá hiếm (popularity 1)."""

FOOD_EXTRA = """- portion_label + portion_grams: chỉ với thực phẩm thường ghi theo cái/quả/bát/cốc/lát (ví dụ "1 quả" 50 cho trứng gà,
  "1 quả" 120 cho chuối tiêu, "1 bát" 150 cho cơm trắng, "1 cốc" 250 cho sữa tươi, "1 lát" 30 cho bánh mì); khối lượng phần
  ăn được, điển hình ở Việt Nam. Thực phẩm thường ghi theo gam (thịt sống, rau, gia vị) thì để null.
- keep=false khi: không ăn trực tiếp và người dùng không tự ghi (nước ướp, nước dùng, men, phụ gia), nội tạng/bộ phận ít
  dùng, đồ hộp hiếm, hoặc popularity 1."""

PRODUCT_EXTRA = """- name_vi: tên sản phẩm tiếng Việt kèm thương hiệu, không kèm dung tích (ví dụ "Sữa tươi tiệt trùng ít đường Vinamilk").
- category: luôn là "Sản phẩm đóng gói".
- portion_label: bao bì của một đơn vị bán ("1 hộp", "1 chai", "1 lon", "1 gói", "1 hũ", "1 thanh", "1 cái") hoặc null.
- keep=false khi: tên/thương hiệu không rõ, không phải thực phẩm, sản phẩm ít người Việt biết, trùng sản phẩm khác,
  hoặc năng lượng /100 vô lý với loại sản phẩm (ví dụ bánh quy 140 kcal/100 g là số của một cái, không phải 100 g)."""


def _line(row_id: str, *parts) -> str:
    return " | ".join([f"id={row_id}"] + [str(part) for part in parts if part not in (None, "")])


def _fmt(value) -> str:
    return "?" if value is None else f"{float(value):g}"


def dish_inputs() -> dict[str, str]:
    """Một dòng cho mỗi tên món (có dấu), bỏ tên nhiễu; id là mã của bản đại diện."""
    picked: dict[str, dict] = {}
    for row in read_json(CACHE / "db_foods.json"):
        if row["item_type"] != "DISH" or NOISY_NAME.search(row["name_vi"]):
            continue
        key = accented(row["name_vi"])
        if key not in picked or (row["is_active"] and not picked[key]["is_active"]):
            picked[key] = row
    lines = {}
    for row in picked.values():
        serving = (row["data_quality"] or {}).get("per_serving_original") or {}
        lines[row["code"]] = _line(row["code"], row["name_vi"], row["name_en"], row["category_vi"],
                                   f"1 suất {_fmt(serving.get('energy_kcal'))} kcal")
    return lines


def food_inputs() -> dict[str, str]:
    lines = {}
    for row in read_json(CACHE / "db_foods.json"):
        if row["item_type"] == "FOOD":
            lines[row["code"]] = _line(row["code"], row["name_vi"], row["name_en"], row["category_vi"],
                                       f"/100 g: {_fmt(row['energy_kcal'])} kcal, P {_fmt(row['protein_g'])}, "
                                       f"C {_fmt(row['carbohydrate_g'])}, F {_fmt(row['fat_g'])}")
    return lines


def product_inputs() -> dict[str, str]:
    from scripts.catalog.products import candidates

    lines = {}
    for product in candidates():
        n = product["nutriments"]
        names = " / ".join(dict.fromkeys(filter(None, (product.get("product_name_vi"), product.get("product_name"),
                                                         product.get("product_name_en")))))
        lines[product["code"]] = _line(product["code"], names, f"brand: {product.get('brands')}",
                                       product.get("quantity"), ", ".join((product.get("categories_tags") or [])[:3]),
                                       f"/100: {_fmt(n.get('energy-kcal_100g'))} kcal")
    return lines


KINDS = {
    "dish": (dish_inputs, DISH_CATEGORIES, DISH_EXTRA),
    "food": (food_inputs, FOOD_CATEGORIES, FOOD_EXTRA),
    "product": (product_inputs, (PRODUCT_CATEGORY,), PRODUCT_EXTRA),
}


def validate(raw: object, wanted: set[str], categories: tuple[str, ...]) -> tuple[dict[str, dict], list[str]]:
    accepted, problems = {}, []
    for item in raw if isinstance(raw, list) else []:
        try:
            annotation = Annotation.model_validate(item)
        except ValidationError as exc:
            problems.append(f"{item.get('id') if isinstance(item, dict) else '?'}: {exc.errors()[0]['msg']}")
            continue
        if annotation.id not in wanted:
            continue
        if annotation.category not in categories:
            problems.append(f"id={annotation.id}: category {annotation.category!r} không có trong danh sách")
            continue
        accepted[annotation.id] = annotation.model_dump()
    return accepted, problems


async def annotate_batch(client, prompt: str, lines: dict[str, str], categories, semaphore) -> dict[str, dict]:
    pending, done = dict(lines), {}
    note = ""
    for _attempt in range(3):
        async with semaphore:
            try:
                raw = await chat_json(client, MODEL, prompt + "\n\n" + "\n".join(pending.values()) + note, 8000)
            except Exception as exc:  # mạng/JSON hỏng: thử lại
                raw, note = [], ""
                print(f"batch error {type(exc).__name__}: {exc}"[:200])
        accepted, problems = validate(raw, set(pending), categories)
        done.update(accepted)
        for key in accepted:
            pending.pop(key)
        if not pending:
            break
        note = "\n\nLần trước bị từ chối hoặc thiếu:\n" + "\n".join(problems[:20] + [f"id={k}: thiếu" for k in pending])
    return done


async def annotate(kind: str, limit: int | None, keys: list[str]) -> None:
    inputs, categories, extra = KINDS[kind]
    lines = inputs()
    if keys:
        lines = {key: line for key, line in lines.items() if key in keys}
    out = CACHE / f"annotations_{kind}.json"
    results = read_json(out) if out.exists() else {}
    todo = {key: line for key, line in lines.items() if key not in results}
    if limit:
        todo = dict(list(todo.items())[:limit])
    prompt = COMMON.format(categories="; ".join(f'"{c}"' for c in categories), extra=extra)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    items = list(todo.items())
    batches = [dict(items[start:start + BATCH]) for start in range(0, len(items), BATCH)]
    async with model_client() as client:
        for result in await asyncio.gather(*(annotate_batch(client, prompt, batch, categories, semaphore)
                                             for batch in batches)):
            results.update(result)
    write_json(out, results)
    print(f"{kind}: annotated {sum(key in results for key in todo)}/{len(todo)} (total {len(results)}) -> {out}")


SPELLINGS = (("pa tê", "pate"), ("patê", "pate"), ("bánh mỳ", "bánh mì"), ("mỳ ", "mì "))


def group_key(name: str) -> tuple[str, ...]:
    """Khoá gộp: tên có dấu, thống nhất cách viết ("pa tê" = "pate", "mỳ" = "mì") và không phụ thuộc thứ tự từ
    ("Phở tái bò" = "Phở bò tái")."""
    text = accented(name) + " "
    for variant, spelling in SPELLINGS:
        text = text.replace(variant, spelling)
    return tuple(sorted(text.split()))


def canonical(candidates: list[dict]) -> list[dict]:
    """Một bản cho mỗi tên (group_key). Ưu tiên: món cơ bản tự tuyển; món nấu có khối lượng kiểm chứng; món (DISH)
    khi tên là món nấu; dòng đang được meal_items trỏ tới (giữ UUID); dòng đang active; mã nhỏ. Tên của các bản còn
    lại thành alias."""
    groups: dict[tuple[str, ...], list[dict]] = {}
    for candidate in candidates:
        groups.setdefault(group_key(candidate["name_vi"]), []).append(candidate)
    chosen = []
    for members in groups.values():
        def rank(candidate: dict):
            cooked = candidate["kind"] == "dish" and candidate["category_vi"] in DISH_CATEGORIES \
                and candidate["category_vi"] != "Trái cây"
            return (not candidate.get("staple"), not (cooked and candidate.get("verified")), not cooked,
                    -candidate["meal_item_count"], not candidate["is_active"], candidate["code"])
        members.sort(key=rank)
        best = dict(members[0])
        name = accented(best["name_vi"])
        others = [text for member in members for text in (member["source_name"], member["name_vi"])]
        best["aliases"] = list(dict.fromkeys(best["aliases"] + [text for text in others if text and accented(text) != name]))
        best["aliases"] += EXTRA_ALIASES.get(best["name_vi"], [])
        best["variants"] = [member["key"] for member in members[1:]]
        chosen.append(best)
    return chosen


# Alias tuyển tay: tên chung người dùng hay gõ mà không bản ghi nào mang đúng tên.
EXTRA_ALIASES = {"Phở bò tái": ["Phở bò"]}


def ranked(items: list[dict]) -> list[dict]:
    """Phổ biến trước; cùng mức phổ biến thì xen kẽ các category (không cắt hạn mức theo thứ tự chữ cái)."""
    position: dict[tuple, int] = {}
    keyed = []
    for item in sorted(items, key=lambda c: (-c["popularity"], -c.get("scans", 0), -c["meal_item_count"], c["name_vi"])):
        tier = (item["kind"], item["popularity"], item["category_vi"])
        position[tier] = position.get(tier, -1) + 1
        keyed.append(((-item["popularity"], position[tier]), item))
    return [item for _key, item in sorted(keyed, key=lambda pair: pair[0])]


def clean_aliases(items: list[dict]) -> list[str]:
    """Bỏ alias trùng tên mục khác hoặc trùng alias của mục khác (so không dấu, như khớp tên). Trả về cảnh báo
    tên trùng nhau khi bỏ dấu."""
    from domains.shared.models import normalize_food_text

    names: dict[str, list[str]] = {}
    for item in items:
        names.setdefault(normalize_food_text(item["name_vi"]), []).append(item["key"])
    usage: dict[str, set[str]] = {}
    for item in items:
        for alias in item["aliases"]:
            usage.setdefault(normalize_food_text(alias), set()).add(item["key"])
    for item in items:
        own = normalize_food_text(item["name_vi"])
        kept, seen = [], set()
        for alias in item["aliases"]:
            plain = normalize_food_text(alias)
            if plain and plain != own and plain not in names and len(usage[plain]) == 1 and plain not in seen:
                kept.append(alias)
                seen.add(plain)
        item["aliases"] = kept
    return [" / ".join(keys) for plain, keys in names.items() if len(keys) > 1]


MUST_HAVE = ("bánh bao nhân thịt", "xôi pate", "phở bò", "cơm trắng", "trứng gà luộc", "ức gà luộc")
MUST_NOT = ("bánh mì chảo",)  # kịch bản demo 1 (biến thể) cần món này thiếu trong catalog
QUOTAS = {"dish": 280, "food": 140, "product": 80}
SELECTION = HERE / "selection.csv"
COLUMNS = ("include", "key", "kind", "popularity", "name_vi", "name_en", "category_vi", "aliases", "portion_label",
           "portion_quantity", "serving_unit", "energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g",
           "source_name", "variants")


def named(item: dict, wanted: tuple[str, ...]) -> bool:
    return any(accented(text) in wanted for text in [item["name_vi"], *item["aliases"]])


def build(force: bool) -> None:
    from scripts.catalog.candidates import all_candidates

    if SELECTION.exists() and not force:
        raise SystemExit(f"{SELECTION} đã có (có thể đã được sửa tay); dùng --force để ghi đè")
    items = canonical(list(all_candidates().values()))
    items = ranked([item for item in items if not named(item, MUST_NOT)])
    counts = dict.fromkeys(QUOTAS, 0)
    for item in items:
        item["include"] = int(named(item, MUST_HAVE) or counts[item["kind"]] < QUOTAS[item["kind"]])
        counts[item["kind"]] += item["include"]
    collisions = clean_aliases([item for item in items if item["include"]])
    missing = [name for name in MUST_HAVE if not any(named(item, (name,)) for item in items if item["include"])]
    with SELECTION.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        order = {"dish": 0, "food": 1, "product": 2}
        for item in sorted(items, key=lambda c: (-c["include"], order[c["kind"]], c["category_vi"], -c["popularity"],
                                                   c["name_vi"])):
            portion = item.get("portion") or {}
            writer.writerow({**{column: item.get(column) for column in COLUMNS},
                             "aliases": " | ".join(item["aliases"]), "variants": " | ".join(item["variants"]),
                             "portion_label": portion.get("label"), "portion_quantity": portion.get("quantity")})
    print(f"{SELECTION}: {sum(i['include'] for i in items)} included of {len(items)} candidates {counts}")
    print(f"must-have missing: {missing or 'none'}")
    print(f"names equal without diacritics ({len(collisions)}): {collisions[:20]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    an = sub.add_parser("annotate")
    an.add_argument("--kind", choices=tuple(KINDS), required=True)
    an.add_argument("--limit", type=int)
    an.add_argument("--keys", default="")
    bu = sub.add_parser("build")
    bu.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "annotate":
        asyncio.run(annotate(args.kind, args.limit, [key for key in args.keys.split(",") if key]))
    else:
        build(args.force)
