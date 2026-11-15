"""Bản ghi ứng viên đầy đủ của catalog v2, ghép từ snapshot nguồn, nhãn LLM và khối lượng đọc từ infographic.

Mỗi ứng viên là một dict theo cột của bảng foods (giá trị trên 100 g/ml) cộng các trường phục vụ chọn lọc
(``popularity``, ``group``, ``meal_item_count``...). ``select_items build`` xếp hạng chúng thành ``selection.csv``;
``build_catalog`` đọc lại ứng viên theo key để ghi JSONL cho migration.
"""
from __future__ import annotations

from scripts.catalog.common import BACKEND, CACHE, HERE, read_json
from scripts.catalog.select_items import (
    DISH_CATEGORIES,
    FOOD_CATEGORIES,
    NOISY_NAME,
    PRODUCT_CATEGORY,
    accented,
)

PORTIONS = BACKEND / "alembic" / "data" / "dish_portions.json"
ATWATER_TOLERANCE = 0.15
MACROS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
# raw_nutrition của bảng món: các khoá năng lượng/macro đã có cột riêng, phần còn lại là vi chất.
DISH_MACRO_KEYS = {"nang-luong": "energy_kcal", "chat-dam": "protein_g", "chat-beo": "fat_g",
                   "chat-bot-duong": "carbohydrate_g", "chat-xo": "fiber_g"}
# Tiếng Anh của bộ category gọn.
CATEGORY_EN = {
    "Phở, bún, miến, mì": "Noodle dishes", "Cơm, xôi": "Rice and sticky rice", "Cháo, súp": "Porridge and soups",
    "Bánh mì, bánh mặn": "Bread and savory cakes", "Món mặn (thịt, cá, trứng)": "Meat, fish and egg dishes",
    "Rau, canh": "Vegetable dishes and soups", "Chè, tráng miệng, bánh ngọt": "Sweet soups, desserts and pastries",
    "Đồ uống": "Beverages", "Trái cây": "Fruits", "Đồ ăn nhanh": "Fast food",
    "Ngũ cốc, khoai củ": "Grains and tubers", "Thịt, cá, trứng, hải sản": "Meat, fish, eggs and seafood",
    "Rau, củ, nấm": "Vegetables and mushrooms", "Sữa, chế phẩm sữa": "Milk and dairy", "Đậu, hạt": "Legumes and nuts",
    "Gia vị, nước chấm": "Condiments and sauces", "Dầu, mỡ, bơ": "Oils and fats",
    "Bánh kẹo, đồ ăn vặt": "Sweets and snacks", PRODUCT_CATEGORY: "Packaged products",
}
BEVERAGES = ("nuoc ", "tra ", "ca phe", "sinh to", "bia", "ruou", "ca cao", "cacao", "milo", "soda", "sua chua uong")


def unit_for(name: str) -> str:
    """ML cho đồ uống (1 g ≈ 1 ml), G cho mọi món ăn khác kể cả chè, kem, canh (như estimate_dish_portions)."""
    from domains.shared.models.catalog import normalize_food_text

    key = normalize_food_text(name) + " "
    if key.startswith(BEVERAGES) or (key.startswith("sua ") and not key.startswith(("sua chua ", "sua bot", "sua dac"))):
        return "ML"
    return "G"


def _num(value) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def atwater_gap(values: dict) -> float:
    """Độ lệch tương đối giữa kcal và 4P + 4C + 9F (5 kcal dung sai cho món gần 0 kcal)."""
    kcal = values["energy_kcal"]
    estimate = 4 * values["protein_g"] + 4 * values["carbohydrate_g"] + 9 * values["fat_g"]
    return max(abs(estimate - kcal) - 5, 0) / max(kcal, 1)


def complete(values: dict) -> list[str] | None:
    """Điền 0 cho đạm/bột đường/chất béo trống (bảng nguồn để trống giá trị không đáng kể) khi năng lượng vẫn khớp
    Atwater; trả về các trường đã điền, hoặc None khi bản ghi không dùng được (thiếu kcal hoặc lệch Atwater)."""
    if values.get("energy_kcal") is None:
        return None
    filled = [field for field in ("protein_g", "carbohydrate_g", "fat_g") if values.get(field) is None]
    values.update({field: 0.0 for field in filled})
    return filled if atwater_gap(values) <= ATWATER_TOLERANCE else None


def _base(kind: str, code: str, annotation: dict, values: dict, unit: str, **extra) -> dict:
    return {
        "key": f"{'DISH' if kind == 'dish' else 'FOOD'}:{code}", "kind": kind, "code": code,
        "item_type": "DISH" if kind == "dish" else "FOOD", "name_vi": annotation["name_vi"].strip(),
        "name_en": annotation["name_en"].strip(), "category_vi": annotation["category"],
        "category_en": CATEGORY_EN[annotation["category"]], "aliases": [a.strip() for a in annotation["aliases"] if a.strip()],
        "popularity": annotation["popularity"], "serving_unit": unit, "serving_size": 100,
        **{field: (round(values[field], 3) if values.get(field) is not None else None) for field in MACROS},
        **extra,
    }


def dishes() -> list[dict]:
    """Món của Viện Dinh dưỡng. Khối lượng suất ưu tiên số kiểm chứng từ infographic (tổng kcal nguyên liệu khớp
    nguồn). Món chỉ có ở bộ VPF (cơm nhà: canh, kho, xào) không đọc được khối lượng món chín, nên dùng khối lượng ước
    lượng của dish_portions.json và gắn cờ: giá trị một suất vẫn là số đo của Viện, chỉ quy đổi theo gam là ước lượng."""
    rows = [row for row in read_json(CACHE / "db_foods.json") if row["item_type"] == "DISH"]
    annotations = read_json(CACHE / "annotations_dish.json")
    weights = read_json(CACHE / "dish_weights.json")
    estimates = {entry["code"]: entry for entry in read_json(PORTIONS)["dishes"].values()}
    representative = {accented(row["name_vi"]): row["code"] for row in rows if row["code"] in annotations}
    out = []
    for row in rows:
        annotation = annotations.get(representative.get(accented(row["name_vi"]), ""))
        weight = weights.get(row["code"], {})
        estimate = estimates.get(row["code"])
        if not annotation or not annotation["keep"] or NOISY_NAME.search(row["name_vi"]):
            continue
        if weight.get("status") == "verified":
            grams, serving = weight["weight_g"], weight["serving"]
            method = {"grams": grams, "method": "sum_of_infographic_ingredients", "verified": True,
                      "listed_kcal": weight.get("listed_kcal"), "model": weight.get("model")}
            components = [{"name": i["name"], "grams": i["grams"], "kcal": i["kcal"]} for i in weight["ingredients"]]
        elif row["code"].startswith("VPF") and estimate:
            original = (row["data_quality"] or {}).get("per_serving_original") or {}
            grams, serving = estimate["weight"], {field: _num(original.get(field)) for field in MACROS}
            method = {"grams": grams, "method": estimate["method"], "verified": False,
                      "note": "per-serving values measured by NIN; serving weight estimated (not published)"}
            components = []
        else:
            continue
        scale = 100 / grams
        values = {field: (value * scale if value is not None else None) for field, value in serving.items()}
        filled = complete(values)
        if filled is None:
            continue
        micronutrients = {}
        for nutrient in row["nutrition_information"].get("raw_nutrition") or []:
            amount = _num(nutrient.get("amount"))
            if nutrient.get("key") in DISH_MACRO_KEYS or amount is None:
                continue
            micronutrients[nutrient["key"]] = {"name": nutrient.get("name"), "name_en": nutrient.get("nameEn"),
                                               "unit": nutrient.get("unit_name"), "amount": round(amount * scale, 6)}
        unit = unit_for(annotation["name_vi"])
        out.append(_base(
            "dish", row["code"], annotation, values, unit,
            source_name=row["name_vi"], meal_item_count=row["meal_item_count"], is_active=row["is_active"],
            verified=method["verified"],
            portion={"label": annotation.get("portion_label") or "1 suất", "quantity": grams, "unit": unit,
                     "source": "nin_infographic" if method["verified"] else method["method"]},
            nutrition_information={"raw_nutrition": row["nutrition_information"].get("raw_nutrition") or [],
                                   "micronutrients": micronutrients, "dish_components": components,
                                   "image": row["nutrition_information"].get("image")},
            data_quality={"source": "vietnam_dish_composition_tables",
                          "original_id": (row["data_quality"] or {}).get("original_id"),
                          "raw_nutrition_basis": "per_serving", "serving_basis": "per_100",
                          "per_serving_original": serving, "serving_weight": method,
                          **({"zero_filled": filled} if filled else {})},
        ))
    return out


def foods() -> list[dict]:
    """Thực phẩm của bảng thành phần: đủ bốn giá trị, giá trị trống chỉ được coi là 0 khi Atwater vẫn khớp."""
    annotations = read_json(CACHE / "annotations_food.json")
    out = []
    for row in read_json(CACHE / "db_foods.json"):
        annotation = annotations.get(row["code"])
        if row["item_type"] != "FOOD" or not annotation or not annotation["keep"]:
            continue
        values = {field: _num(row[field]) for field in MACROS}
        filled = complete(values)
        if filled is None:
            continue
        portion = None
        if annotation.get("portion_label") and annotation.get("portion_grams"):
            portion = {"label": annotation["portion_label"], "quantity": annotation["portion_grams"],
                       "unit": row["serving_unit"], "source": "typical_weight_llm"}
        out.append(_base(
            "food", row["code"], annotation, values, row["serving_unit"],
            source_name=row["name_vi"], meal_item_count=row["meal_item_count"], is_active=row["is_active"],
            portion=portion,
            nutrition_information={key: row["nutrition_information"][key]
                                   for key in ("raw_nutrition", "micronutrients") if key in row["nutrition_information"]},
            data_quality={"source": "vietnam_food_composition_tables",
                          "original_id": (row["data_quality"] or {}).get("original_id"),
                          **({"zero_filled": filled} if filled else {})},
        ))
    return out


def products() -> list[dict]:
    from scripts.catalog.products import candidates as off_candidates

    path = CACHE / "annotations_product.json"
    annotations = read_json(path) if path.exists() else {}
    out = []
    for product in off_candidates():
        annotation = annotations.get(product["code"])
        if not annotation or not annotation["keep"]:
            continue
        size, unit = product["size"] or (None, "ML" if annotation["name_vi"].lower().startswith(
            ("sữa tươi", "nước", "trà", "cà phê", "bia")) else "G")
        out.append({**_base(
            "product", f"OFF-{product['code']}", annotation, product["macros"], unit,
            source_name=product.get("product_name_vi") or product.get("product_name"), meal_item_count=0,
            is_active=False,
            portion={"label": f"{annotation.get('portion_label') or '1 gói'} {size:g} {unit.lower()}",
                     "quantity": size, "unit": unit, "source": "package"} if size else None,
            nutrition_information={},
            data_quality={"source": "open_food_facts", "barcode": product["code"], "brand": product["brand"],
                          "brands": product.get("brands"), "license": "ODbL (data), CC BY-SA (images)",
                          "url": f"https://world.openfoodfacts.org/product/{product['code']}"},
            image_source=product.get("image_front_url"),
        ), "scans": product.get("unique_scans_n") or 0})
    return out


def staples() -> list[dict]:
    """Món cơ bản bảng của Viện không có (cơm trắng đã nấu, ức gà luộc...), số liệu USDA FoodData Central."""
    out = []
    for item in read_json(HERE / "staples.json"):
        annotation = {"name_vi": item["name_vi"], "name_en": item["name_en"], "category": item["category"],
                      "aliases": item["aliases"], "popularity": 5}
        out.append(_base(
            "food", item["code"], annotation, item, item["serving_unit"], source_name=item["name_vi"],
            meal_item_count=0, is_active=False,
            portion={**item["portion"], "unit": item["serving_unit"], "source": "typical_weight"},
            nutrition_information={}, data_quality={"source": "usda_fooddata_central", "reference": item["source"]},
            staple=True,
        ))
    return out


def all_candidates() -> dict[str, dict]:
    out = {}
    for candidate in dishes() + foods() + products() + staples():
        assert candidate["category_vi"] in DISH_CATEGORIES + FOOD_CATEGORIES + (PRODUCT_CATEGORY,)
        out[candidate["key"]] = candidate
    return out
