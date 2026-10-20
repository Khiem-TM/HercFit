"""Actual food/training logs; callers cannot supply totals or legacy flags."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from schemas.activity import ExerciseActivityInput, ExerciseActivityRead, FoodPortionInput, FoodPortionRead, NutritionTotals
from schemas.common import EntityRead, InputSchema, Name
from schemas.foods import Nutrient
from schemas.tracking import DEFAULT_TIMEZONE, JournalQuery, TimeZoneName, VersionedRequest

DurationSeconds = Annotated[Decimal, Field(gt=0, lt=1000000000, max_digits=12, decimal_places=3, allow_inf_nan=False)]


class MealCreate(InputSchema):
    name: Name
    consumed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: str | None = None
    source_entry_id: UUID | None = None
    items: Annotated[list[FoodPortionInput], Field(min_length=1)]


class TrainingCreate(InputSchema):
    name: Name
    started_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: AwareDatetime | None = None
    duration_seconds: DurationSeconds | None = None
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: str | None = None
    source_entry_id: UUID | None = None
    items: Annotated[list[ExerciseActivityInput], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_duration(self):
        if self.ended_at is not None and self.started_at is not None:
            duration = Decimal(str((self.ended_at - self.started_at).total_seconds())).quantize(Decimal("0.001"))
            if duration <= 0 or duration >= 1000000000:
                raise ValueError("ended_at must follow started_at within the supported duration")
            if self.duration_seconds is not None and self.duration_seconds != duration:
                raise ValueError("duration_seconds does not match the timestamps")
            self.duration_seconds = duration
        return self


class MealReplace(VersionedRequest, MealCreate):
    consumed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def non_null_time(self):
        if "consumed_at" in self.model_fields_set and self.consumed_at is None:
            raise ValueError("consumed_at may be omitted but cannot be null")
        return self


class TrainingReplace(VersionedRequest, TrainingCreate):
    started_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def non_null_time(self):
        if "started_at" in self.model_fields_set and self.started_at is None:
            raise ValueError("started_at may be omitted but cannot be null")
        return self


class JournalRead(EntityRead):
    user_id: UUID
    name: str
    timezone: str
    note: str | None
    source_entry_id: UUID | None
    replaces_id: UUID | None
    source: Literal["USER", "LEGACY_IMPORT"]
    detail_status: Literal["DETAILED", "AGGREGATE_ONLY"]


class MealItemRead(FoodPortionRead):
    meal_id: UUID


class TrainingItemRead(ExerciseActivityRead):
    training_id: UUID


class MealRead(NutritionTotals, JournalRead):
    consumed_at: AwareDatetime
    nutrition_incomplete: bool
    items: list[MealItemRead]


class TrainingRead(JournalRead):
    started_at: AwareDatetime
    ended_at: AwareDatetime | None
    duration_seconds: DurationSeconds | None
    energy_kcal: Nutrient | None
    calories_incomplete: bool
    items: list[TrainingItemRead]
