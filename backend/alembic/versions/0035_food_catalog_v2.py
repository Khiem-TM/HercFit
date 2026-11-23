"""Catalog thực phẩm v2: ~500 mục đã tuyển thay cho bảng SYSTEM cũ.

Dữ liệu nằm trong alembic/data/food_catalog_v2.jsonl, do pipeline backend/scripts/catalog dựng:

* món của Viện Dinh dưỡng, giá trị /100 g suy từ khối lượng suất = tổng khối lượng nguyên liệu in trên infographic
  (tổng kcal nguyên liệu khớp năng lượng một suất của nguồn trong 5 %);
* thực phẩm của bảng thành phần Viện Dinh dưỡng, tên tự nhiên, tên gốc giữ làm alias;
* sản phẩm đóng gói từ Open Food Facts; vài món cơ bản thiếu trong bảng Viện lấy từ USDA FoodData Central;
* mỗi mục một ảnh thật đã duyệt (Cloudinary) và alias để khớp tên khi ghi bữa.

Dòng SYSTEM cùng (item_type, code) được cập nhật tại chỗ nên giữ UUID; dòng mới có UUID suy định từ (item_type,
code). Mọi dòng SYSTEM active khác bị vô hiệu hoá (không xoá) và đánh dấu data_quality.retired_by = 'catalog_v2';
meal_items giữ food_id và ảnh chụp món như cũ. Dòng CUSTOM không bị đụng tới.

Downgrade bật lại các dòng đã vô hiệu hoá và tắt các dòng mới chèn; dòng đã cập nhật giữ giá trị v2 (sao lưu DB trước
khi nâng cấp nếu cần khôi phục đầy đủ).
"""
import json
import unicodedata
import uuid
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0035_food_catalog_v2"
down_revision = "0034_health_sync_fences"
branch_labels = depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "food_catalog_v2.jsonl"
NAMESPACE = uuid.UUID("6f0d3a8e-1c55-4b8e-9a51-6b1f2f0c9a10")
NUTRIENTS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
COLUMNS = ("code", "name_vi", "name_en", "category_vi", "category_en", *NUTRIENTS, "image_url", "image_public_id")
JSON_COLUMNS = ("nutrition_information", "data_quality", "portions")


def _normalize(value: str) -> str:
    """Như domains.shared.models.normalize_food_text (migration không import code ứng dụng)."""
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def _params(item: dict) -> dict:
    search = " ".join(part for part in (item["code"], item["name_vi"], item.get("name_en"), item.get("category_vi"),
                                        item.get("category_en")) if part)
    return {
        **{column: item.get(column) for column in COLUMNS},
        **{column: json.dumps(item[column], ensure_ascii=False) for column in JSON_COLUMNS},
        "item_type": item["item_type"], "serving_unit": item["serving_unit"],
        "normalized_name_vi": _normalize(item["name_vi"]),
        "normalized_name_en": _normalize(item["name_en"]) if item.get("name_en") else None,
        "normalized_search_text": _normalize(search),
    }


ASSIGN = ", ".join(f"{column} = :{column}" for column in COLUMNS + ("normalized_name_vi", "normalized_name_en",
                                                                     "normalized_search_text"))
ASSIGN += ", " + ", ".join(f"{column} = CAST(:{column} AS jsonb)" for column in JSON_COLUMNS)
ASSIGN += (", item_type = CAST(:item_type AS food_item_type), serving_unit = CAST(:serving_unit AS food_serving_unit),"
           " serving_size = 100, is_active = true")
INSERT_COLUMNS = COLUMNS + ("normalized_name_vi", "normalized_name_en", "normalized_search_text") + JSON_COLUMNS


def upgrade():
    bind = op.get_bind()
    items = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not items:
        raise RuntimeError(f"{DATA.name} is empty")
    existing = {(row.item_type, row.code): row.id for row in bind.execute(sa.text(
        "SELECT id::text AS id, item_type::text AS item_type, code FROM foods WHERE source_type = 'SYSTEM'"))}
    kept = []
    for item in items:
        params = _params(item)
        food_id = existing.get((item["item_type"], item["code"]))
        if food_id:
            bind.execute(sa.text(f"UPDATE foods SET {ASSIGN}, version_id = version_id + 1, updated_at = now() "
                                 "WHERE id = CAST(:id AS uuid)"), {**params, "id": food_id})
        else:
            food_id = str(uuid.uuid5(NAMESPACE, f"food:{item['item_type']}:{item['code']}"))
            params["data_quality"] = json.dumps({**item["data_quality"], "inserted_by": "catalog_v2"}, ensure_ascii=False)
            values = ", ".join(f"CAST(:{c} AS jsonb)" if c in JSON_COLUMNS else f":{c}" for c in INSERT_COLUMNS)
            bind.execute(sa.text(
                f"INSERT INTO foods (id, source_type, item_type, serving_unit, serving_size, {', '.join(INSERT_COLUMNS)}) "
                f"VALUES (CAST(:id AS uuid), 'SYSTEM', CAST(:item_type AS food_item_type), "
                f"CAST(:serving_unit AS food_serving_unit), 100, {values})"), {**params, "id": food_id})
        kept.append(food_id)
        bind.execute(sa.text("DELETE FROM foods_aliases WHERE entity_id = CAST(:id AS uuid)"), {"id": food_id})
        aliases = dict.fromkeys(a for a in (_normalize(alias) for alias in item.get("aliases") or []) if a)
        for alias in aliases:
            bind.execute(sa.text("INSERT INTO foods_aliases (entity_id, normalized_alias) VALUES (CAST(:id AS uuid), :a)"),
                         {"id": food_id, "a": alias})
    bind.execute(sa.text(
        "UPDATE foods SET is_active = false, version_id = version_id + 1, updated_at = now(), "
        "data_quality = coalesce(data_quality, '{}'::jsonb) || '{\"retired_by\": \"catalog_v2\"}'::jsonb "
        "WHERE source_type = 'SYSTEM' AND is_active AND NOT (id::text = ANY(:kept))"), {"kept": kept})


def downgrade():
    op.execute("UPDATE foods SET is_active = true, version_id = version_id + 1, updated_at = now(), "
               "data_quality = data_quality - 'retired_by' WHERE data_quality ->> 'retired_by' = 'catalog_v2'")
    op.execute("UPDATE foods SET is_active = false, version_id = version_id + 1, updated_at = now() "
               "WHERE data_quality ->> 'inserted_by' = 'catalog_v2'")
