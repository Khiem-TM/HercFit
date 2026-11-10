"""Mọi thực phẩm tính dinh dưỡng theo 100 g hoặc 100 ml; bỏ căn cứ theo suất (PORTION).

* Món PORTION (bảng món ăn Viện Dinh dưỡng chỉ công bố giá trị cho "1 suất") được quy về 100 g/100 ml bằng khối
  lượng suất trong alembic/data/dish_portions.json (scripts/estimate_dish_portions.py: suy ra từ bản ghi cùng tên
  theo 100 g khi khớp, còn lại do model ước lượng và code kiểm tra). Năng lượng, macro và vi chất nhân 100/khối lượng;
  raw_nutrition giữ nguyên bản gốc của nguồn. data_quality ghi khối lượng, phương pháp và giá trị theo suất ban đầu.
  "1 suất" trở thành một khẩu phần hộ gia đình (portions) đo bằng g/ml.
* meal_items chỉ còn G/ML: SERVING được quy ra g/ml (dinh dưỡng giữ nguyên); món PORTION từng bị ghi bằng gam được tính
  lại theo khối lượng suất, rồi tổng của bữa được tính lại. Ảnh chụp món trong mục nhật ký theo căn cứ mới.
* food_serving_unit bỏ PORTION; cột portion_weight_g bị xoá.

Downgrade chỉ khôi phục lược đồ; giá trị theo suất ban đầu vẫn nằm trong data_quality.per_serving_original.
"""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0032_food_mass_basis"
down_revision = "0031_health_alerts"
branch_labels = depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data" / "dish_portions.json"
NUTRIENTS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
STEP = Decimal("0.000001")


def _scaled(value, factor):
    return None if value is None else (Decimal(value) * factor).quantize(STEP, rounding=ROUND_HALF_UP)


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _convert_foods(bind) -> dict[str, dict]:
    rows = bind.execute(sa.text(
        "SELECT id::text AS id, serving_size, nutrition_information, data_quality, "
        + ", ".join(NUTRIENTS) + " FROM foods WHERE serving_unit::text = 'PORTION'")).mappings().all()
    if not rows:
        return {}
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    estimates = payload["dishes"]
    missing = [row["id"] for row in rows if row["id"] not in estimates]
    if missing:
        raise RuntimeError(f"{len(missing)} PORTION foods have no serving weight in {DATA.name} (e.g. {missing[:3]}); "
                           "run `python -m scripts.estimate_dish_portions` first")
    converted = {}
    for row in rows:
        estimate = estimates[row["id"]]
        weight, unit = Decimal(str(estimate["weight"])), estimate["unit"]
        # Giá trị đã lưu mô tả serving_size suất (luôn là 1 với dữ liệu hiện có).
        factor = Decimal(100) / (weight * Decimal(row["serving_size"] or 1))
        values = {field: _scaled(row[field], factor) for field in NUTRIENTS}
        info = dict(row["nutrition_information"] or {})
        if isinstance(info.get("micronutrients"), dict):
            info["micronutrients"] = {
                key: {**item, "amount": float(_scaled(Decimal(str(item["amount"])), factor))}
                if isinstance(item, dict) and isinstance(item.get("amount"), (int, float)) else item
                for key, item in info["micronutrients"].items()
            }
        quality = dict(row["data_quality"] or {})
        quality["serving_basis"] = "per_100"
        if "raw_nutrition" in info:
            quality["raw_nutrition_basis"] = "per_serving"
        quality["per_serving_original"] = {field: None if row[field] is None else float(row[field]) for field in NUTRIENTS}
        quality["portion_estimate"] = {"weight": float(weight), "unit": unit, "method": estimate["method"],
                                       **({"model": payload.get("model")} if estimate["method"] == "llm_estimate" else {})}
        portions = [{"label": estimate["label"], "quantity": float(weight), "unit": unit, "source": estimate["method"]}]
        bind.execute(sa.text(
            "UPDATE foods SET serving_size = 100, serving_unit = CAST(:unit AS food_serving_unit), "
            + ", ".join(f"{field} = :{field}" for field in NUTRIENTS)
            + ", nutrition_information = CAST(:info AS jsonb), data_quality = CAST(:quality AS jsonb), "
            "portions = CAST(:portions AS jsonb), version_id = version_id + 1, updated_at = now() "
            "WHERE id = CAST(:id AS uuid)"),
            {"id": row["id"], "unit": unit, **values, "info": _json(info), "quality": _json(quality),
             "portions": _json(portions)})
        converted[row["id"]] = {"weight": weight * Decimal(row["serving_size"] or 1), "unit": unit,
                                "original": {field: row[field] for field in NUTRIENTS}, "values": values,
                                "portions": portions}
    return converted


def _repair_meal_items(bind, converted: dict[str, dict]) -> set[str]:
    # Gồm cả mục ghi trước khi món được đánh dấu là theo suất: ảnh chụp của chúng ghi nhầm "theo 100 g".
    ids = list(converted)
    items = bind.execute(sa.text(
        "SELECT id::text AS id, meal_id::text AS meal_id, food_id::text AS food_id, quantity, unit, food_snapshot "
        "FROM meal_items WHERE unit NOT IN ('G', 'ML') OR food_snapshot ->> 'serving_unit' = 'PORTION' "
        "OR food_snapshot ? 'portion_weight_g' OR food_id::text = ANY(:ids) OR food_snapshot ->> 'id' = ANY(:ids)"),
        {"ids": ids}).mappings().all()
    meals = set()
    for item in items:
        snapshot = dict(item["food_snapshot"] or {})
        snapshot.pop("portion_weight_g", None)
        food = converted.get(item["food_id"] or snapshot.get("id"))
        quantity, unit, nutrients = Decimal(item["quantity"]), item["unit"], None
        if food is not None:
            if unit == "SERVING":
                quantity *= food["weight"]
            else:
                # Từng ghi bằng gam cho món theo suất: tính lại theo khối lượng suất (1 g ≈ 1 ml).
                nutrients = {field: _scaled(food["original"][field], quantity / food["weight"]) for field in NUTRIENTS}
            unit = food["unit"]
            snapshot.update(serving_size="100", serving_unit=unit, portions=food["portions"],
                            **{field: None if value is None else str(value) for field, value in food["values"].items()})
        elif unit == "SERVING":
            # Món theo g/ml: một SERVING từng có nghĩa là serving_size của món.
            if snapshot.get("serving_unit") not in ("G", "ML") or not snapshot.get("serving_size"):
                raise RuntimeError(f"meal item {item['id']} is logged in SERVING without a usable serving basis")
            quantity *= Decimal(str(snapshot["serving_size"]))
            unit = snapshot["serving_unit"]
        params = {"id": item["id"], "quantity": quantity.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                  "unit": unit, "snapshot": _json(snapshot)}
        assignments = "quantity = :quantity, unit = :unit, food_snapshot = CAST(:snapshot AS jsonb)"
        if nutrients is not None:
            params.update(nutrients, incomplete=any(value is None for value in nutrients.values()))
            assignments += ", " + ", ".join(f"{field} = :{field}" for field in NUTRIENTS)
            assignments += ", nutrition_incomplete = :incomplete"
            meals.add(item["meal_id"])
        bind.execute(sa.text(f"UPDATE meal_items SET {assignments}, updated_at = now() WHERE id = CAST(:id AS uuid)"),
                     params)
    return meals


def _retotal(bind, meals: set[str]) -> None:
    """Tổng của bữa như sum_known: một món chưa biết làm tổng tương ứng thành chưa biết."""
    sums = ", ".join(f"CASE WHEN bool_and({field} IS NOT NULL) THEN sum({field}) END AS {field}" for field in NUTRIENTS)
    assignments = ", ".join(f"{field} = t.{field}" for field in NUTRIENTS)
    incomplete = " OR ".join(f"t.{field} IS NULL" for field in NUTRIENTS)
    for meal_id in meals:
        bind.execute(sa.text(
            f"UPDATE meals m SET {assignments}, nutrition_incomplete = ({incomplete}), updated_at = now() "
            f"FROM (SELECT {sums} FROM meal_items WHERE meal_id = CAST(:id AS uuid)) t WHERE m.id = CAST(:id AS uuid)"),
            {"id": meal_id})


def upgrade():
    bind = op.get_bind()
    converted = _convert_foods(bind)
    _retotal(bind, _repair_meal_items(bind, converted))

    op.execute("ALTER TABLE meal_items DROP CONSTRAINT IF EXISTS ck_meal_items_unit")
    op.execute("ALTER TABLE meal_items ADD CONSTRAINT ck_meal_items_unit CHECK (unit IN ('G', 'ML'))")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portion_weight")
    op.execute("ALTER TABLE foods DROP COLUMN IF EXISTS portion_weight_g")
    # PostgreSQL không xoá được giá trị enum: dựng lại kiểu không có PORTION.
    op.execute("ALTER TABLE foods ALTER COLUMN serving_unit DROP DEFAULT")
    op.execute("ALTER TYPE food_serving_unit RENAME TO food_serving_unit_old")
    op.execute("CREATE TYPE food_serving_unit AS ENUM ('G', 'ML')")
    op.execute("ALTER TABLE foods ALTER COLUMN serving_unit TYPE food_serving_unit "
               "USING serving_unit::text::food_serving_unit")
    op.execute("ALTER TABLE foods ALTER COLUMN serving_unit SET DEFAULT 'G'")
    op.execute("DROP TYPE food_serving_unit_old")


def downgrade():
    op.execute("ALTER TYPE food_serving_unit ADD VALUE IF NOT EXISTS 'PORTION'")
    op.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS portion_weight_g numeric(12,4)")
    op.execute("ALTER TABLE foods ADD CONSTRAINT ck_foods_portion_weight "
               "CHECK (portion_weight_g IS NULL OR (portion_weight_g > 0 AND portion_weight_g < 100000))")
    op.execute("ALTER TABLE meal_items DROP CONSTRAINT IF EXISTS ck_meal_items_unit")
    op.execute("ALTER TABLE meal_items ADD CONSTRAINT ck_meal_items_unit CHECK (unit IN ('G', 'ML', 'SERVING'))")
