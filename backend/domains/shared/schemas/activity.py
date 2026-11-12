"""Thành phần thực phẩm/bài tập có thứ tự, dùng lại cho lịch và nhật ký thực tế."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from domains.catalog.schemas.exercises import (
    CalorieEstimate,
    ExerciseActivityInput,  # noqa: F401 (re-export cho domains.training.schemas.trainings)
    ExercisePerformanceRead,
)
from domains.catalog.schemas.foods import Nutrient, ServingSize
from domains.shared.schemas.common import EntityRead, InputSchema, JsonObject

NUTRIENT_FIELDS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")


class NutritionTotals(InputSchema):
    energy_kcal: Nutrient | None = None
    protein_g: Nutrient | None = None
    carbohydrate_g: Nutrient | None = None
    fat_g: Nutrient | None = None
    fiber_g: Nutrient | None = None


class FoodPortionInput(InputSchema):
    food_id: UUID
    quantity: ServingSize
    unit: Literal["G", "ML"]
    note: str | None = None


class FoodPortionRead(NutritionTotals, EntityRead):
    food_id: UUID | None
    position: int
    quantity: Decimal
    unit: Literal["G", "ML"]
    food_snapshot: JsonObject
    nutrition_information: JsonObject
    nutrition_incomplete: bool
    note: str | None


class ExerciseActivityRead(EntityRead):
    exercise_id: UUID | None
    position: int
    exercise_snapshot: JsonObject
    performance: ExercisePerformanceRead
    calorie_estimate: CalorieEstimate
    energy_kcal: Nutrient | None
    note: str | None
