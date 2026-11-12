"""Nhật ký ăn uống/tập luyện thực tế; bên gọi không được truyền tổng hay cờ cũ.

Tách ra từ schemas.journals trong đợt tổ chức lại theo miền."""
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from domains.shared.schemas.activity import FoodPortionInput, FoodPortionRead, NutritionTotals
from domains.shared.schemas.common import InputSchema, Name
from domains.shared.schemas.journal import JournalRead
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName, VersionedRequest


class MealCreate(InputSchema):
    name: Name
    consumed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: str | None = None
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
