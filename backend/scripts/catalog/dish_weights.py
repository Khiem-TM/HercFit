"""Bước 2: khối lượng một suất của món, đọc từ infographic của Viện Dinh dưỡng.

Infographic của mỗi món liệt kê nguyên liệu kèm khối lượng (g), đa số kèm năng lượng (kcal) từng nguyên liệu. Khối
lượng suất là tổng khối lượng nguyên liệu, nên giá trị trên 100 g suy ra từ dữ liệu công bố thay vì ước lượng.

Model nhìn ảnh chỉ chép bảng; code tính tổng và kiểm tra:

* ``verified``: có kcal từng nguyên liệu và tổng kcal lệch không quá 5 % so với năng lượng một suất của nguồn;
* ``plausible``: không có cột kcal, nhưng mật độ năng lượng và khối lượng macro hợp lý;
* ``rejected``: còn lại (không đọc được, tổng lệch, mật độ vô lý). Món bị loại không được chọn vào catalog.

    python -m scripts.catalog.dish_weights download                   # tải infographic (miễn phí)
    python -m scripts.catalog.dish_weights extract --codes HAN-113016,SFF-112032 --model google/gemma-4-31b-it
    python -m scripts.catalog.dish_weights extract --codes-file codes.txt
"""
from __future__ import annotations

import argparse
import asyncio
import mimetypes
import re
import time
from pathlib import Path

import httpx

from scripts.catalog.common import (
    CACHE,
    NIN_BASE,
    USER_AGENT,
    chat_json,
    image_part,
    model_client,
    read_json,
    write_json,
)

IMAGES = CACHE / "infographics"
OUT = CACHE / "dish_weights.json"
DEFAULT_MODEL = "google/gemma-4-31b-it"
KCAL_TOLERANCE = 0.05
MIN_DENSITY, MAX_DENSITY = 10, 600

PROMPT = """Ảnh là infographic món ăn của Viện Dinh dưỡng Việt Nam. Chép lại bảng thành phần món ăn (nguyên liệu).
Bảng có thể ở dạng bảng "Thành phần món ăn | Trọng lượng (g) | Năng lượng (Kcal)" (có thể chia hai cột trái/phải),
hoặc dạng danh sách "Thành phần: - Tên: 120g".
Trả về DUY NHẤT một JSON:
{"ingredients": [{"name": "<tên nguyên liệu>", "grams": <số gam>, "kcal": <số kcal hoặc null nếu ảnh không ghi>}],
 "badge_kcal": <số kcal tổng in trên ảnh hoặc null>}
Chép đúng số trên ảnh (dấu phẩy thập phân đổi thành dấu chấm). Không bỏ sót dòng nào, không tự thêm nguyên liệu.
Nếu ảnh không có bảng thành phần thì trả về {"ingredients": [], "badge_kcal": null}."""


def dish_rows() -> list[dict]:
    """Mọi dòng DISH của snapshot DB có infographic."""
    return [row for row in read_json(CACHE / "db_foods.json")
            if row["item_type"] == "DISH" and (row["nutrition_information"] or {}).get("image")]


def image_path(row: dict) -> Path:
    suffix = Path(row["nutrition_information"]["image"]).suffix.lower() or ".png"
    return IMAGES / f"{row['code']}{suffix}"


def download() -> None:
    rows = dish_rows()
    IMAGES.mkdir(parents=True, exist_ok=True)
    fetched = missing = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        for row in rows:
            path = image_path(row)
            if path.exists() and path.stat().st_size:
                continue
            response = client.get(NIN_BASE + row["nutrition_information"]["image"])
            if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
                path.write_bytes(response.content)
                fetched += 1
            else:
                missing += 1
            time.sleep(1)
    have = sum(1 for row in rows if image_path(row).exists())
    print(f"{have}/{len(rows)} infographics in {IMAGES} (fetched {fetched}, missing {missing})")


def serving(row: dict) -> dict:
    """Giá trị một suất gốc: per_serving_original (sau 0032) hoặc chính các cột khi dòng chưa đổi căn cứ."""
    original = (row["data_quality"] or {}).get("per_serving_original")
    fields = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
    source = original if original else row
    return {field: (float(source[field]) if source.get(field) is not None else None) for field in fields}


def _number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(match.group().replace(",", ".")) if match else None


def judge(row: dict, reading: dict) -> dict:
    """Tính khối lượng suất từ bảng đã chép và xếp loại verified / plausible / rejected."""
    per_serving = serving(row)
    items = []
    for item in reading.get("ingredients") or []:
        grams = _number(item.get("grams"))
        if grams and grams > 0:
            items.append({"name": str(item.get("name") or "").strip(), "grams": grams, "kcal": _number(item.get("kcal"))})
    result = {"code": row["code"], "name_vi": row["name_vi"], "ingredients": items,
              "badge_kcal": _number(reading.get("badge_kcal")), "serving": per_serving}
    if not items:
        return {**result, "status": "rejected", "reason": "không đọc được bảng thành phần"}
    weight = round(sum(item["grams"] for item in items), 1)
    kcal = per_serving["energy_kcal"]
    result["weight_g"] = weight
    if not kcal:
        return {**result, "status": "rejected", "reason": "nguồn không có năng lượng một suất"}
    density = kcal * 100 / weight
    result["kcal_per_100g"] = round(density, 1)
    macros = sum(per_serving[field] or 0 for field in ("protein_g", "carbohydrate_g", "fat_g", "fiber_g"))
    if macros > weight:
        return {**result, "status": "rejected", "reason": f"macro {macros:g} g lớn hơn khối lượng {weight:g} g"}
    if not (MIN_DENSITY <= density <= MAX_DENSITY or (kcal < 20 and density < MIN_DENSITY)):
        return {**result, "status": "rejected", "reason": f"mật độ {density:.0f} kcal/100 g ngoài khoảng"}
    if all(item["kcal"] is not None for item in items):
        listed = sum(item["kcal"] for item in items)
        result["listed_kcal"] = round(listed, 1)
        if abs(listed - kcal) <= KCAL_TOLERANCE * kcal:
            return {**result, "status": "verified"}
        return {**result, "status": "rejected", "reason": f"tổng kcal nguyên liệu {listed:g} lệch nguồn {kcal:g}"}
    return {**result, "status": "plausible"}


async def read_table(client: httpx.AsyncClient, model: str, path: Path) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    reading = await chat_json(client, model, [{"type": "text", "text": PROMPT}, image_part(path.read_bytes(), mime)],
                              max_tokens=1500)
    if not isinstance(reading, dict):
        raise ValueError("JSON không phải object")
    return reading


async def extract(codes: list[str], model: str, out: Path, concurrency: int) -> None:
    rows = {row["code"]: row for row in dish_rows()}
    results = read_json(out) if out.exists() else {}
    todo = [code for code in codes if code in rows and image_path(rows[code]).exists()
            and results.get(code, {}).get("model") != model]
    semaphore = asyncio.Semaphore(concurrency)

    async def one(client: httpx.AsyncClient, code: str) -> None:
        async with semaphore:
            try:
                reading = await read_table(client, model, image_path(rows[code]))
                results[code] = {**judge(rows[code], reading), "model": model}
            except Exception as exc:  # mạng/định dạng: ghi lý do, chạy lại sẽ thử tiếp
                results[code] = {"code": code, "name_vi": rows[code]["name_vi"], "status": "error",
                                 "reason": f"{type(exc).__name__}: {exc}"[:200], "model": None}

    async with model_client() as client:
        await asyncio.gather(*(one(client, code) for code in todo))
    write_json(out, results)
    picked = [results[code] for code in codes if code in results]
    counts: dict[str, int] = {}
    for result in picked:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    print(f"{len(todo)} read with {model}; statuses over {len(picked)} requested: {counts} -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download")
    ex = sub.add_parser("extract")
    ex.add_argument("--codes", default="")
    ex.add_argument("--codes-file", type=Path)
    ex.add_argument("--model", default=DEFAULT_MODEL)
    ex.add_argument("--out", type=Path, default=OUT)
    ex.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.command == "download":
        download()
    else:
        wanted = [code.strip() for code in args.codes.split(",") if code.strip()]
        if args.codes_file:
            wanted += [line.strip() for line in args.codes_file.read_text().splitlines() if line.strip()]
        asyncio.run(extract(wanted, args.model, args.out, args.concurrency))
