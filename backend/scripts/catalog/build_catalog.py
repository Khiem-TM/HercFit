"""Bước 5: ``selection.csv`` đã duyệt + ảnh đã upload → ``alembic/data/food_catalog_v2.jsonl`` cho migration 0035.

Cột sửa tay trong selection.csv được áp lên ứng viên: include, name_vi, name_en, category_vi, aliases (phân cách
" | "), portion_label, portion_quantity. Trước khi ghi, mọi bất biến phải đạt:

* tên duy nhất, cả có dấu lẫn không dấu; alias không trùng tên hay alias của mục khác (so không dấu);
* đủ năng lượng, đạm, bột đường, chất béo; năng lượng khớp Atwater trong 15 % (dung sai 5 kcal);
* khẩu phần cùng đơn vị với căn cứ; category thuộc bộ cố định;
* mỗi mục một ảnh, không hai mục dùng chung ảnh;
* có đủ các mục demo/eval cần (MUST_HAVE), không có mục cấm (MUST_NOT).

    python -m scripts.catalog.build_catalog items      # danh sách cho find_images
    python -m scripts.catalog.build_catalog --check    # chỉ kiểm tra
    python -m scripts.catalog.build_catalog            # kiểm tra rồi ghi JSONL
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

from domains.shared.models.catalog import normalize_food_text
from scripts.catalog.candidates import (
    ATWATER_TOLERANCE,
    CATEGORY_EN,
    MACROS,
    all_candidates,
    atwater_gap,
)
from scripts.catalog.common import BACKEND, CACHE, read_json, write_json
from scripts.catalog.select_items import CATEGORIES, MUST_HAVE, MUST_NOT, SELECTION, accented

OUT = BACKEND / "alembic" / "data" / "food_catalog_v2.jsonl"


def selected() -> list[dict]:
    """Ứng viên có include = 1, đã áp cột sửa tay."""
    candidates = all_candidates()
    items = []
    with SELECTION.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["include"].strip() != "1":
                continue
            if row["key"] not in candidates:
                raise SystemExit(f"{row['key']}: không còn trong ứng viên (snapshot/nhãn đã đổi?)")
            item = dict(candidates[row["key"]])
            item.update(name_vi=row["name_vi"].strip(), name_en=row["name_en"].strip() or None,
                        category_vi=row["category_vi"].strip(),
                        aliases=[alias.strip() for alias in row["aliases"].split("|") if alias.strip()])
            item["category_en"] = CATEGORY_EN.get(item["category_vi"])
            if row["portion_label"].strip() and row["portion_quantity"].strip():
                item["portion"] = {**(item.get("portion") or {"source": "manual"}), "label": row["portion_label"].strip(),
                                   "quantity": float(row["portion_quantity"]), "unit": item["serving_unit"]}
            elif not row["portion_label"].strip():
                item["portion"] = None
            items.append(item)
    return items


def violations(items: list[dict], images: dict) -> list[str]:
    problems = []
    accented_names, plain_names, alias_owner = {}, {}, {}
    for item in items:
        for table, value in ((accented_names, accented(item["name_vi"])), (plain_names, normalize_food_text(item["name_vi"]))):
            if value in table:
                problems.append(f"tên trùng: {item['key']} và {table[value]} ({value})")
            table[value] = item["key"]
    for item in items:
        for alias in item["aliases"]:
            plain = normalize_food_text(alias)
            if plain in plain_names and plain_names[plain] != item["key"]:
                problems.append(f"alias {alias!r} của {item['key']} trùng tên {plain_names[plain]}")
            if alias_owner.setdefault(plain, item["key"]) != item["key"]:
                problems.append(f"alias {alias!r} dùng cho cả {item['key']} và {alias_owner[plain]}")
        if any(item.get(field) is None for field in MACROS[:4]):
            problems.append(f"{item['key']}: thiếu năng lượng/macro")
        elif atwater_gap(item) > ATWATER_TOLERANCE:
            problems.append(f"{item['key']}: năng lượng lệch Atwater {atwater_gap(item):.0%}")
        if item["category_vi"] not in CATEGORIES:
            problems.append(f"{item['key']}: category {item['category_vi']!r} không thuộc bộ cố định")
        portion = item.get("portion")
        if portion and (portion["unit"] != item["serving_unit"] or not portion["quantity"] > 0):
            problems.append(f"{item['key']}: khẩu phần {portion} không hợp lệ")
        if item["key"] not in images:
            problems.append(f"{item['key']}: chưa có ảnh")
    public_ids = {}
    for key, image in images.items():
        if public_ids.setdefault(image["public_id"], key) != key:
            problems.append(f"ảnh dùng chung: {key} và {public_ids[image['public_id']]}")

    def has(name: str) -> bool:
        return any(accented(text) == name for item in items for text in [item["name_vi"], *item["aliases"]])
    problems += [f"thiếu mục bắt buộc: {name}" for name in MUST_HAVE if not has(name)]
    problems += [f"có mục cấm: {name}" for name in MUST_NOT if has(name)]
    return problems


def record(item: dict, image: dict) -> dict:
    portion = item.get("portion")
    return {
        "item_type": item["item_type"], "code": item["code"], "name_vi": item["name_vi"], "name_en": item["name_en"],
        "category_vi": item["category_vi"], "category_en": item["category_en"], "serving_unit": item["serving_unit"],
        **{field: item.get(field) for field in MACROS},
        "nutrition_information": item["nutrition_information"],
        "data_quality": {**item["data_quality"], "catalog": "v2", "image_source": image.get("source_url")},
        "portions": [{key: portion[key] for key in ("label", "quantity", "unit", "source") if portion.get(key) is not None}]
        if portion else [],
        "aliases": item["aliases"], "image_url": image["url"], "image_public_id": image["public_id"],
    }


def items_for_images() -> None:
    out = [{"key": item["key"], "name_vi": item["name_vi"], "name_en": item["name_en"], "kind": item["kind"],
            "image_url": item.get("image_source")} for item in selected()]
    write_json(CACHE / "items.json", out)
    print(f"{len(out)} items -> {CACHE / 'items.json'}")


def main(check: bool) -> None:
    items = selected()
    uploaded_path = CACHE / "uploaded.json"
    uploaded = read_json(uploaded_path) if uploaded_path.exists() else {}
    images = {item["key"]: uploaded[item["key"]] for item in items if item["key"] in uploaded}
    problems = violations(items, images)
    counts = {kind: sum(item["kind"] == kind for item in items) for kind in ("dish", "food", "product")}
    print(f"{len(items)} items {counts}, {len(images)} with images, {len(problems)} violations")
    for problem in problems[:60]:
        print(" -", problem)
    if problems:
        sys.exit(1)
    if not check:
        OUT.write_text("".join(json.dumps(record(item, images[item["key"]]), ensure_ascii=False, sort_keys=True) + "\n"
                               for item in sorted(items, key=lambda i: i["key"])), encoding="utf-8")
        print(f"-> {OUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("items",))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.command == "items":
        items_for_images()
    else:
        main(args.check)
