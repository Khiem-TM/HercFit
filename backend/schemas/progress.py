"""Read-only comparisons; no persisted progress counters or calorie estimates."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from schemas.common import ReadSchema


class MetricProgress(ReadSchema):
    target: Decimal | None = None
    actual: Decimal | None
    known_total: Decimal
    missing_count: int = Field(ge=0)


class DailyProgressRead(ReadSchema):
    date: date
    meal_count: int
    training_count: int
    calories_in: MetricProgress
    exercise_calories: MetricProgress
    protein_g: MetricProgress
    carbohydrate_g: MetricProgress
    fat_g: MetricProgress
    fiber_g: MetricProgress
    calories_out_target: Decimal | None
    # Exercise logs alone do not measure total daily expenditure.
    calories_out_actual: None = None


class ProgressRead(ReadSchema):
    timezone: str
    start_date: date
    end_date: date
    days: list[DailyProgressRead]


class PlanProgressRead(ProgressRead):
    plan_id: UUID
