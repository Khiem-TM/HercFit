"""Bước 1: chụp lại nguồn dữ liệu vào backend/.cache/catalog (không tốn phí).

* ``db_foods.json``: mọi dòng SYSTEM trong bảng foods (cả dòng đã gộp), kèm số meal_items đang trỏ tới. Dòng FOOD
  giữ nguyên số liệu gốc của bảng thành phần thực phẩm Viện Dinh dưỡng (migration 0032 chỉ đổi dòng DISH), còn
  ``raw_nutrition`` của DISH là giá trị một suất gốc.
* ``nin_dishes.json``: toàn bộ món trên API công khai của viendinhduong.vn (giá trị một suất, đường dẫn infographic).
* ``off_vn.json``: sản phẩm bán tại Việt Nam trên Open Food Facts đã đủ bảng dinh dưỡng, của thương hiệu phổ biến
  (``products.BRANDS``).

    python -m scripts.catalog.snapshot              # cả ba nguồn
    python -m scripts.catalog.snapshot --only off
"""
from __future__ import annotations

import argparse
import time

import httpx
import psycopg
from psycopg.rows import dict_row

from core.database import get_postgres_connection_string
from scripts.catalog.common import CACHE, NIN_BASE, USER_AGENT, write_json

FOODS = """select f.id::text, f.code, f.item_type::text, f.name_vi, f.name_en, f.category_vi, f.category_en,
  f.serving_size, f.serving_unit::text, f.energy_kcal, f.protein_g, f.carbohydrate_g, f.fat_g, f.fiber_g,
  f.nutrition_information, f.data_quality, f.portions, f.image_url, f.is_active,
  (select count(*) from meal_items m where m.food_id = f.id) as meal_item_count
from foods f where f.source_type = 'SYSTEM' order by f.item_type, f.code"""

OFF_FIELDS = ",".join((
    "code", "product_name", "product_name_vi", "product_name_en", "generic_name", "brands", "quantity",
    "serving_size", "serving_quantity", "product_quantity", "nutrition_data_per", "nutriments", "categories_tags",
    "image_front_url", "unique_scans_n", "popularity_key", "countries_tags", "last_modified_t",
))


def snapshot_db() -> int:
    with psycopg.connect(get_postgres_connection_string(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(FOODS)
        rows = cur.fetchall()
    write_json(CACHE / "db_foods.json", rows)
    return len(rows)


def snapshot_nin(client: httpx.Client) -> int:
    dishes, page, last = [], 1, 1
    while page <= last:
        response = client.get(f"{NIN_BASE}/api/fe/tool/getPageFoodData", params={"page": page})
        response.raise_for_status()
        body = response.json()
        dishes.extend(body["data"])
        last = body["last_page"]
        page += 1
        time.sleep(1)
    write_json(CACHE / "nin_dishes.json", dishes)
    return len(dishes)


def _get_json(client: httpx.Client, url: str, params: dict | None = None) -> dict | None:
    for attempt in range(5):
        response = client.get(url, params=params)
        if response.status_code == 404:
            return None
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        time.sleep(10 * (attempt + 1))  # OFF hay trả 503 khi quá tải
    response.raise_for_status()
    raise RuntimeError(f"{url} không trả JSON")


def front_image(code: str, images: dict) -> str | None:
    """URL ảnh mặt trước đã chọn trên OFF (ưu tiên tiếng Việt), dựng từ trường images như trang sản phẩm của OFF."""
    keys = sorted((key for key in images or {} if key.startswith("front_")), key=lambda key: key != "front_vi")
    if not keys or not images[keys[0]].get("rev"):
        return None
    folder = "/".join((code[0:3], code[3:6], code[6:9], code[9:])) if len(code) > 8 else code
    return f"https://images.openfoodfacts.org/images/products/{folder}/{keys[0]}.{images[keys[0]]['rev']}.full.jpg"


def snapshot_off(client: httpx.Client) -> int:
    """API search v2 và product API của OFF thường xuyên 503/429, nên lấy cả danh sách lẫn dinh dưỡng qua
    search.openfoodfacts.org (search-a-licious), khoảng 100 sản phẩm mỗi request."""
    products, page, pages = [], 1, 1
    query = 'countries_tags:"en:vietnam" AND states_tags:"en:nutrition-facts-completed"'
    while page <= pages:
        body = _get_json(client, "https://search.openfoodfacts.org/search",
                         {"q": query, "page_size": 100, "page": page, "fields": OFF_FIELDS + ",images"})
        pages = body["page_count"]
        for hit in body["hits"]:
            images = hit.pop("images", None)
            brands = hit.get("brands")
            products.append({**hit, "brands": ", ".join(brands) if isinstance(brands, list) else brands,
                             "image_front_url": front_image(hit["code"], images)})
        page += 1
        time.sleep(1)
    write_json(CACHE / "off_vn.json", products)
    return len(products)


def main(only: str | None) -> None:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        if only in (None, "db"):
            print(f"db_foods: {snapshot_db()} rows")
        if only in (None, "nin"):
            print(f"nin_dishes: {snapshot_nin(client)} dishes")
        if only in (None, "off"):
            print(f"off_vn: {snapshot_off(client)} products")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("db", "nin", "off"))
    main(parser.parse_args().only)
