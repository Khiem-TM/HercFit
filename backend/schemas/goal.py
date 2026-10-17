from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from schemas.common import EntityRead, FiniteNumber, JsonObject, Name, NonBlank, PartialSchema, Version
from schemas.enums import GoalStatus


class TargetBase(PartialSchema):
    non_nullable = frozenset({"baseline"})
    unit: NonBlank
    baseline: FiniteNumber | None = None


class ScalarTarget(TargetBase):
    operator: Literal["eq", "gte", "lte"]
    value: FiniteNumber


class RangeTarget(TargetBase):
    operator: Literal["range"]
    min: FiniteNumber
    max: FiniteNumber

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


GoalTarget = Annotated[ScalarTarget | RangeTarget, Field(discriminator="operator")]


class GoalCreate(PartialSchema):
    title: Name
    start_date: date
    target_date: date | None = None
    description: str | None = None
    goal_types: list[NonBlank] = Field(default_factory=list)
    targets: dict[NonBlank, GoalTarget] = Field(default_factory=dict)
    context: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.start_date is not None and self.target_date is not None and self.target_date < self.start_date:
            raise ValueError("target_date must not be before start_date")
        return self


class GoalUpdate(GoalCreate):
    non_nullable = frozenset({"title", "start_date"})
    title: Name | None = None
    start_date: date | None = None


class GoalUpdateRequest(GoalUpdate):
    expected_version_id: Version

    def to_payload(self):
        return self.model_dump(mode="python", exclude_unset=True, exclude={"expected_version_id"})


class GoalRead(GoalCreate, EntityRead):
    user_id: UUID
    status: GoalStatus
