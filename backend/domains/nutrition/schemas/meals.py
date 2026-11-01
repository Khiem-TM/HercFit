"""Actual food/training logs; callers cannot supply totals or legacy flags.

Split from schemas.journals in the domain reorganization."""
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID
from pydantic import AwareDatetime, Field, model_validator
from domains.shared.schemas.activity import FoodPortionInput, FoodPortionRead, NutritionTotals
from domains.shared.schemas.common import InputSchema, Name
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName, VersionedRequest
from domains.shared.schemas.journal import JournalRead


class MealCreate(InputSchema):
    name: Name
    consumed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: str | None = None
    source_entry_id: UUID | None = None
    items: Annotated[list[FoodPortionInput], Field(min_length=1)]

class MealReplace(VersionedRequest, MealCreate):
    consumed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def non_null_time(self):
        if "consumed_at" in self.model_fields_set and self.consumed_at is None:
            raise ValueError("consumed_at may be omitted but cannot be null")
        return self

class MealItemRead(FoodPortionRead):
    meal_id: UUID

class MealRead(NutritionTotals, JournalRead):
    consumed_at: AwareDatetime
    nutrition_incomplete: bool
    items: list[MealItemRead]
