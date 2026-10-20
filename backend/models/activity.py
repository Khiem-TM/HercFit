"""Catalog snapshot builders shared by planned and actual activity items."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID as PyUUID

from fastapi import HTTPException
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from schemas.activity import FoodPortionInput, NUTRIENT_FIELDS, NutritionTotals
from schemas.exercises import ExerciseActivityInput, ExerciseRead
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


# Cấu trúc bài tập thể dục
class ExerciseActivityMixin:
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="SET NULL"), nullable=True,
    )
    exercise_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    performance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calorie_estimate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    )


async def build_food_item(session: AsyncSession, user_id: PyUUID, payload) -> dict[str, Any]:
    from models.foods import FoodItem

    item = FoodPortionInput.model_validate(payload)
    food = await FoodItem.get_visible_by_id(session, item.food_id, user_id=user_id)
    if food is None:
        raise HTTPException(404, "Food not found")
    if item.unit != "SERVING" and item.unit != food.serving_unit:
        raise HTTPException(422, "Portion unit must match the food serving unit; density is not inferred")
    known = any(getattr(food, field) is not None for field in NUTRIENT_FIELDS)
    if known and food.serving_size is None:
        raise HTTPException(422, "Nutrition requires a known serving basis")
    factor = item.quantity if item.unit == "SERVING" else (item.quantity / food.serving_size if food.serving_size else None)
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


async def build_exercise_item(session: AsyncSession, user_id: PyUUID, payload) -> dict[str, Any]:
    from models.exercises import Exercise

    item = ExerciseActivityInput.model_validate(payload)
    exercise = await Exercise.get_visible_by_id(session, item.exercise_id, user_id=user_id)
    if exercise is None:
        raise HTTPException(404, "Exercise not found")
    if item.performance.kind != exercise.kind:
        raise HTTPException(422, "Performance kind must match the exercise")
    return {
        "exercise_id": exercise.id,
        "exercise_snapshot": ExerciseRead.model_validate(exercise).model_dump(mode="json"),
        "performance": item.performance.model_dump(mode="json"),
        "calorie_estimate": item.calorie_estimate.model_dump(mode="json"),
        "energy_kcal": item.calorie_estimate.kcal,
        "note": item.note,
    }


def sum_known(items, fields=NUTRIENT_FIELDS) -> dict[str, Decimal | None]:
    """Unknown components make the corresponding total unknown, never zero."""
    return {
        field: sum((item[field] for item in items), Decimal(0))
        if all(item[field] is not None for item in items) else None
        for field in fields
    }
