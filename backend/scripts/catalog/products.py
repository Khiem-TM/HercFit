"""Sản phẩm đóng gói ứng viên từ snapshot Open Food Facts (``off_vn.json``).

Chỉ giữ sản phẩm của thương hiệu phổ biến tại Việt Nam, đủ bốn giá trị trên 100 g/ml và năng lượng khớp Atwater.
Dung tích đọc được thì có khẩu phần ("1 hộp 180 ml"). Số liệu OFF do cộng đồng nhập, đôi khi là giá trị một gói ghi
nhầm thành /100 g; nhãn LLM (select_items, kind product) loại các giá trị vô lý với loại sản phẩm.
"""
from __future__ import annotations

import re

from domains.shared.models.catalog import normalize_food_text
from scripts.catalog.common import CACHE, read_json

BRANDS = (
    "vinamilk", "th true", "th milk", "dutch lady", "co gai ha lan", "nutifood", "moc chau", "nestle", "milo",
    "ovaltine", "acecook", "hao hao", "omachi", "masan", "chin su", "chinsu", "kokomi", "vifon", "cung dinh", "coca",
    "pepsi", "7up", "sting", "number 1", "number1", "tan hiep phat", "c2", "urc", "oishi", "orion", "kinh do", "cosy",
    "vissan", "ba huan", "vinacafe", "trung nguyen", "g7", "nescafe", "highlands", "lavie", "la vie", "aquafina",
    "red bull", "redbull", "revive", "lipton", "fami", "vinasoy", "vfresh", "yomost", "probi", "kun", "lothamilk",
    "meiji", "lotte", "bibica", "hai ha", "richy", "choco pie", "chocopie", "poca", "lay's", "lays", "oreo", "solite",
    "custas", "tipo", "afc", "cp", "maggi", "knorr", "cholimex", "nam ngu", "tuong an", "neptune", "simply",
    "tribeco", "wake up", "boncha", "mirinda", "sprite", "fanta", "tiger", "heineken", "sabeco", "bia saigon",
    "hanoi beer", "habeco", "dalat milk", "love'in farm", "hoff", "ajinomoto", "vital", "tipo", "goute", "slide",
)
QUANTITY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|l|cl|g|kg)\b", re.I)
ATWATER_TOLERANCE = 0.15  # như build_catalog (5 kcal dung sai)


def brand_of(brands: str) -> str | None:
    """Thương hiệu phổ biến đầu tiên có trong chuỗi brands của OFF (so như đầu một từ)."""
    text = " " + normalize_food_text(brands or "").replace(",", " ") + " "
    return next((brand for brand in BRANDS if f" {brand} " in text), None)


def quantity(product: dict) -> tuple[float, str] | None:
    """Khối lượng/dung tích một đơn vị bán, theo g hoặc ml. "4 x 180 ml" là 180 ml."""
    match = QUANTITY.search(product.get("quantity") or "")
    if not match:
        return None
    value, unit = float(match.group(1).replace(",", ".")), match.group(2).lower()
    value *= {"kg": 1000, "l": 1000, "cl": 10}.get(unit, 1)
    if not 5 <= value <= 3000:
        return None
    return round(value, 1), ("ML" if unit in ("ml", "l", "cl") else "G")


def macros(product: dict) -> dict[str, float] | None:
    n = product.get("nutriments") or {}
    fields = {"energy_kcal": "energy-kcal_100g", "protein_g": "proteins_100g", "carbohydrate_g": "carbohydrates_100g",
              "fat_g": "fat_100g"}
    values = {}
    for field, source in fields.items():
        value = n.get(source)
        if not isinstance(value, (int, float)) or value < 0:
            return None
        values[field] = float(value)
    fiber = n.get("fiber_100g")
    values["fiber_g"] = float(fiber) if isinstance(fiber, (int, float)) and fiber >= 0 else None
    return values


def atwater_ok(values: dict[str, float]) -> bool:
    kcal = values["energy_kcal"]
    estimate = 4 * values["protein_g"] + 4 * values["carbohydrate_g"] + 9 * values["fat_g"]
    return max(abs(estimate - kcal) - 5, 0) <= ATWATER_TOLERANCE * max(kcal, 1)


DENSE = ("en:biscuits", "en:cakes", "en:snacks", "en:chips", "en:crisps", "en:confectioneries", "en:chocolates",
         "en:candies", "en:nuts", "en:instant-noodles", "en:dried-products")
DRINKS = ("en:beverages", "en:milks", "en:sodas", "en:waters", "en:juices", "en:drinkable-yogurts")


def plausible(product: dict, values: dict[str, float]) -> bool:
    """Bắt số liệu một gói nhập nhầm thành /100 g: đồ khô (bánh, snack, kẹo, hạt, mì gói) dưới 300 kcal/100 g, đồ
    uống trên 120 kcal/100 ml."""
    tags = product.get("categories_tags") or []
    if any(tag in tags for tag in DENSE) and values["energy_kcal"] < 300:
        return False
    return not (any(tag in tags for tag in DRINKS) and not any(tag in tags for tag in DENSE)
                and values["energy_kcal"] > 120)


def candidates() -> list[dict]:
    """Sản phẩm dùng được, mỗi (thương hiệu, tên, dung tích) một bản, phổ biến nhất trước. Thiếu dung tích thì không
    có khẩu phần (ghi theo g/ml); thiếu ảnh mặt trước thì find_images tìm qua Tavily."""
    picked: dict[tuple, dict] = {}
    for product in read_json(CACHE / "off_vn.json"):
        name = product.get("product_name_vi") or product.get("product_name") or product.get("product_name_en")
        brand = brand_of(product.get("brands") or "")
        values = macros(product)
        size = quantity(product)
        if not (name and brand and values) or not atwater_ok(values) or not plausible(product, values):
            continue
        key = (brand, normalize_food_text(name), size)
        if key not in picked:
            picked[key] = {**product, "brand": brand, "macros": values, "size": size}
    return sorted(picked.values(), key=lambda p: -(p.get("unique_scans_n") or 0))
