"""DTO schemas representing responses returned by the internal HercFit CRUD Backend API."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BackendDTO(BaseModel):
    """Base DTO allowing extra fields from upstream Backend responses."""

    model_config = ConfigDict(extra="allow")


class UserProfileDTO(BackendDTO):
    id: UUID | str
    email: str
    fullname: str | None = None
    gender: str | None = None
    dob: date | None = None
    is_onboarding: bool = False
    personal_info: dict[str, Any] = Field(default_factory=dict)


class GoalDTO(BackendDTO):
    id: UUID | str
    user_id: UUID | str | None = None
    title: str
    description: str | None = None
    start_date: date | str | None = None
    target_date: date | str | None = None
    status: str | None = None
    targets: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class BodyMetricDTO(BackendDTO):
    id: UUID | str
    user_id: UUID | str | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    body_fat_pct: float | None = None
    muscle_mass_kg: float | None = None
    recorded_at: datetime | str | None = None
    is_active: bool = True


class ProgressOverviewDTO(BackendDTO):
    user_id: UUID | str | None = None
    current_goal: dict[str, Any] | None = None
    latest_metrics: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class CatalogItemDTO(BackendDTO):
    id: UUID | str
    name_vi: str | None = None
    name_en: str | None = None
    calories_kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    category: str | None = None


__all__ = [
    "BackendDTO",
    "BodyMetricDTO",
    "CatalogItemDTO",
    "GoalDTO",
    "ProgressOverviewDTO",
    "UserProfileDTO",
]

