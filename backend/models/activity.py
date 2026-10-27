"""Catalog snapshot builders shared by planned (prescription) and actual (performance) items."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID as PyUUID

from fastapi import HTTPException
from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from schemas.activity import FoodPortionInput, NUTRIENT_FIELDS, NutritionTotals
from schemas.exercises import ExerciseActivityInput, ExerciseKind, ExercisePrescriptionInput, ExerciseRead
from services.training_metrics import estimate_kcal, item_metrics
from schemas.foods import FoodRead

# Cột dinh dưỡng vĩ mô --> Được sử dụng tại FoodPortionMixin và Meal (nhật ký bữa ăn)
class NutrientColumns:
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


# Cấu trúc khẩu phần món ăn
class FoodPortionMixin(NutrientColumns):
    position: Mapped[int] = mapped_column(Integer, nullable=False) # thứ tự của món ăn trong bữa ăn
    food_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"), nullable=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    food_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    nutrition_information: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    nutrition_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# Tham chiếu bài tập chung cho lịch tập và nhật ký thực tế
class ExerciseRefMixin:
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="SET NULL"), nullable=True,
    )
    exercise_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# Kết quả thực tế: chi tiết theo môn nằm trong JSONB, chỉ số tổng hợp do server tính
# và lưu thành cột để analytics chỉ cần SUM/MAX thay vì đọc JSONB.
class ExerciseActualMixin(ExerciseRefMixin):
    performance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calorie_estimate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kind: Mapped[ExerciseKind | None] = mapped_column(Enum(ExerciseKind, name="exercise_kind", validate_strings=True, create_type=False), nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    distance_meters: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    elevation_gain_meters: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    volume_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    best_e1rm_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    hard_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    working_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)


# Chỉ định trong lịch tập: khoảng reps, %1RM, bước interval... không phải kết quả.
class ExercisePlanMixin(ExerciseRefMixin):
    prescription: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


ITEM_METRIC_FIELDS = ("duration_seconds", "distance_meters", "elevation_gain_meters", "volume_kg", "best_e1rm_kg", "hard_sets", "working_sets")


def nutrient_constraints(prefix: str):
    return tuple(CheckConstraint(f"{field} IS NULL OR ({field} >= 0 AND {field} < 1000000000000)", name=f"ck_{prefix}_{field}") for field in NUTRIENT_FIELDS)


def food_item_constraints(prefix: str):
    return (
        *nutrient_constraints(prefix),
        CheckConstraint("position >= 0", name=f"ck_{prefix}_position"),
        CheckConstraint("quantity > 0 AND quantity < 100000000", name=f"ck_{prefix}_quantity"),
        CheckConstraint("unit IN ('G', 'ML', 'SERVING')", name=f"ck_{prefix}_unit"),
        CheckConstraint("jsonb_typeof(food_snapshot) = 'object'", name=f"ck_{prefix}_snapshot"),
        CheckConstraint("jsonb_typeof(nutrition_information) = 'object'", name=f"ck_{prefix}_nutrition"),
    )


def exercise_item_constraints(prefix: str):
    return (
        CheckConstraint("position >= 0", name=f"ck_{prefix}_position"),
        CheckConstraint("energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)", name=f"ck_{prefix}_energy"),
        *(CheckConstraint(f"jsonb_typeof({field}) = 'object'", name=f"ck_{prefix}_{field}")
          for field in ("exercise_snapshot", "performance", "calorie_estimate")),
        *(CheckConstraint(f"{field} IS NULL OR {field} >= 0", name=f"ck_{prefix}_{field}") for field in ITEM_METRIC_FIELDS),
    )


def prescription_item_constraints(prefix: str):
    return (
        CheckConstraint("position >= 0", name=f"ck_{prefix}_position"),
        *(CheckConstraint(f"jsonb_typeof({field}) = 'object'", name=f"ck_{prefix}_{field}")
          for field in ("exercise_snapshot", "prescription")),
    )


async def build_food_item(session: AsyncSession, user_id: PyUUID, payload) -> dict[str, Any]:
    from models.foods import FoodItem

    item = FoodPortionInput.model_validate(payload)
    food = await FoodItem.get_visible_by_id(session, item.food_id, user_id=user_id)
    if food is None:
        raise HTTPException(404, "Food not found")
    factor = portion_factor(food, item.unit, item.quantity)
    values = {
        field: (getattr(food, field) * factor).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if getattr(food, field) is not None and factor is not None else None
        for field in NUTRIENT_FIELDS
    }
    totals = NutritionTotals.model_validate(values).model_dump()
    return {
        **item.model_dump(), **totals,
        "food_snapshot": FoodRead.model_validate(food).model_dump(mode="json"),
        # This is the catalog's per-serving information, not an untyped scaled total.
        "nutrition_information": {"basis": "catalog_serving", "values": food.nutrition_information},
        "nutrition_incomplete": any(value is None for value in totals.values()),
    }


def portion_factor(food, unit: str, quantity: Decimal) -> Decimal | None:
    """Multiplier from the stored nutrient basis to the logged amount.

    G/ML foods store values per serving_size grams/millilitres. PORTION foods
    store values per serving (suất); grams are accepted only when the serving's
    gram weight is known, because scaling a per-serving value as if it were
    per 100 g silently multiplies energy several times over.
    """
    from schemas.enums import FoodServingUnit

    known = any(getattr(food, field) is not None for field in NUTRIENT_FIELDS)
    if food.serving_unit == FoodServingUnit.PORTION:
        if unit == "SERVING":
            return quantity / (food.serving_size or Decimal(1))
        if unit == "G" and food.portion_weight_g:
            return quantity / food.portion_weight_g
        raise HTTPException(422, "This dish has nutrition per serving only; log it in SERVING units "
                                 "or record the serving's gram weight first")
    if unit != "SERVING" and unit != food.serving_unit:
        raise HTTPException(422, "Portion unit must match the food serving unit; density is not inferred")
    if known and food.serving_size is None:
        raise HTTPException(422, "Nutrition requires a known serving basis")
    return quantity if unit == "SERVING" else (quantity / food.serving_size if food.serving_size else None)


async def _visible_exercise(session: AsyncSession, user_id: PyUUID, exercise_id, kind):
    from models.exercises import Exercise

    exercise = await Exercise.get_visible_by_id(session, exercise_id, user_id=user_id)
    if exercise is None:
        raise HTTPException(404, "Exercise not found")
    if kind != exercise.kind:
        raise HTTPException(422, "Performance kind must match the exercise")
    return exercise


async def build_exercise_item(session: AsyncSession, user_id: PyUUID, payload, *, bodyweight_kg: float | None = None) -> dict[str, Any]:
    item = ExerciseActivityInput.model_validate(payload)
    exercise = await _visible_exercise(session, user_id, item.exercise_id, item.performance.kind)
    calorie = item.calorie_estimate.model_dump(mode="json")
    if item.calorie_estimate.kcal is None:
        # A user/device value always wins; otherwise attach a reproducible estimate.
        calorie = estimate_kcal(item.performance, exercise.configuration, bodyweight_kg) or calorie
    metrics = item_metrics(item.performance, exercise.configuration, bodyweight_kg=bodyweight_kg)
    return {
        "exercise_id": exercise.id,
        "exercise_snapshot": ExerciseRead.model_validate(exercise).model_dump(mode="json"),
        "performance": item.performance.model_dump(mode="json"),
        "calorie_estimate": calorie,
        "energy_kcal": None if calorie.get("kcal") is None else Decimal(str(calorie["kcal"])),
        "kind": exercise.kind,
        **{field: None if metrics[field] is None else Decimal(str(metrics[field])) if field not in {"hard_sets", "working_sets"} else metrics[field]
           for field in ITEM_METRIC_FIELDS},
        "note": item.note,
    }


async def build_prescription_item(session: AsyncSession, user_id: PyUUID, payload) -> dict[str, Any]:
    item = ExercisePrescriptionInput.model_validate(payload)
    exercise = await _visible_exercise(session, user_id, item.exercise_id, item.prescription.kind)
    return {
        "exercise_id": exercise.id,
        "exercise_snapshot": ExerciseRead.model_validate(exercise).model_dump(mode="json"),
        "prescription": item.prescription.model_dump(mode="json"),
        "note": item.note,
    }


def sum_known(items, fields=NUTRIENT_FIELDS) -> dict[str, Decimal | None]:
    """Unknown components make the corresponding total unknown, never zero."""
    return {
        field: sum((item[field] for item in items), Decimal(0))
        if all(item[field] is not None for item in items) else None
        for field in fields
    }
