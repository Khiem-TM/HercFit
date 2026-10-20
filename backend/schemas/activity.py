"""Reusable ordered food/exercise components for schedules and actual logs."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from schemas.common import EntityRead, InputSchema, JsonObject
from schemas.exercises import CalorieEstimate, ExerciseActivityInput, ExercisePerformanceRead
from schemas.foods import Nutrient, ServingSize

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
    unit: Literal["G", "ML", "SERVING"]
    note: str | None = None


class FoodPortionRead(NutritionTotals, EntityRead):
    food_id: UUID | None
    position: int
    quantity: Decimal
    unit: Literal["G", "ML", "SERVING"]
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
