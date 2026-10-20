"""Typed, complete-replacement contracts for plans and dated schedules."""

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from schemas.activity import ExerciseActivityInput, ExerciseActivityRead, FoodPortionInput, FoodPortionRead
from schemas.common import EntityRead, InputSchema, JsonObject, Name, NonBlank, Pagination, Version
from schemas.tracking import TimeZoneName, VersionedRequest

PlanStatus = Literal["ACTIVE", "ENDED"]
TargetAmount = Annotated[Decimal, Field(ge=0, lt=1000000000, max_digits=12, decimal_places=3, allow_inf_nan=False)]


class MetricTarget(InputSchema):
    value: TargetAmount
    unit: NonBlank
    period: Literal["DAY", "WEEK", "PLAN"]


class DateSpan(InputSchema):
    name: Name
    start_date: date
    end_date: date
    note: str | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class PlanInput(DateSpan):
    """Public manual plan input; provenance and snapshots are server-owned."""
    goal_id: UUID
    timezone: TimeZoneName = "Asia/Ho_Chi_Minh"
    calories_in_kcal: TargetAmount | None = None
    calories_out_kcal: TargetAmount | None = None
    exercise_calories_kcal: TargetAmount | None = None
    protein_g: TargetAmount | None = None
    carbohydrate_g: TargetAmount | None = None
    fat_g: TargetAmount | None = None
    fiber_g: TargetAmount | None = None
    extra_metrics: dict[NonBlank, MetricTarget] = Field(default_factory=dict)


class PlanCreate(PlanInput):
    source: JsonObject = Field(default_factory=dict)


class ManualPlanReplace(VersionedRequest, PlanInput):
    pass


class PlanReplace(VersionedRequest, PlanCreate):
    pass


class PlanEnd(InputSchema):
    expected_version_id: Version
    reason: NonBlank = "USER_ENDED"


class PlanRead(PlanCreate, EntityRead):
    user_id: UUID
    status: PlanStatus
    ended_at: AwareDatetime | None
    end_reason: str | None
    replaces_id: UUID | None
    profile_snapshot: JsonObject
    body_metric_snapshot: JsonObject | None
    goal_snapshot: JsonObject


class PlanQuery(Pagination):
    status: PlanStatus | None = None
    goal_id: UUID | None = None
    plan_id: UUID | None = None


class ScheduleEntryCreate(InputSchema):
    scheduled_date: date
    scheduled_time: time | None = None
    label: Name
    note: str | None = None

    @model_validator(mode="after")
    def local_time(self):
        if self.scheduled_time is not None and self.scheduled_time.tzinfo is not None:
            raise ValueError("scheduled_time is local to the parent plan timezone")
        return self


class MealPlanEntryCreate(ScheduleEntryCreate):
    meal_type: Annotated[NonBlank, Field(max_length=100)] | None = None
    items: Annotated[list[FoodPortionInput], Field(min_length=1)]


class TrainingPlanEntryCreate(ScheduleEntryCreate):
    is_rest: bool = False
    items: list[ExerciseActivityInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def rest_or_exercises(self):
        if self.is_rest and self.items:
            raise ValueError("A rest entry cannot contain exercises")
        if not self.is_rest and not self.items:
            raise ValueError("A training entry must contain at least one exercise")
        return self


class ScheduleCreate(DateSpan):
    @model_validator(mode="after")
    def entries_within_dates(self):
        for entry in self.entries:
            if not self.start_date <= entry.scheduled_date <= self.end_date:
                raise ValueError("Every entry must fall inside the schedule date range")
        return self


class MealPlanCreate(ScheduleCreate):
    entries: Annotated[list[MealPlanEntryCreate], Field(min_length=1)]


class TrainingPlanCreate(ScheduleCreate):
    entries: Annotated[list[TrainingPlanEntryCreate], Field(min_length=1)]


class MealPlanReplace(VersionedRequest, MealPlanCreate):
    pass


class TrainingPlanReplace(VersionedRequest, TrainingPlanCreate):
    pass


class MealPlanItemRead(FoodPortionRead):
    entry_id: UUID
    position: int


class TrainingPlanItemRead(ExerciseActivityRead):
    entry_id: UUID
    position: int


class MealPlanEntryRead(ScheduleEntryCreate, EntityRead):
    meal_plan_id: UUID
    meal_type: str | None
    position: int
    items: list[MealPlanItemRead]


class TrainingPlanEntryRead(ScheduleEntryCreate, EntityRead):
    training_plan_id: UUID
    is_rest: bool
    position: int
    items: list[TrainingPlanItemRead]


class ScheduleRead(DateSpan, EntityRead):
    user_id: UUID
    plan_id: UUID
    timezone: TimeZoneName
    status: PlanStatus
    ended_at: AwareDatetime | None
    end_reason: str | None
    replaces_id: UUID | None


class MealPlanRead(ScheduleRead):
    entries: list[MealPlanEntryRead]


class TrainingPlanRead(ScheduleRead):
    entries: list[TrainingPlanEntryRead]
