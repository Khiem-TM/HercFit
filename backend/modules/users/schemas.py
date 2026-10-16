"""Pydantic schemas for User Profile and Body Metrics endpoints."""

from datetime import datetime
from pydantic import BaseModel, Field


class UserProfileUpdate(BaseModel):
    full_name: str | None = None
    age: int | None = Field(default=None, ge=1, le=120)
    height_cm: float | None = Field(default=None, gt=0)
    fitness_goal: str | None = Field(
        default=None, description="e.g. fat_loss, muscle_gain, maintenance, endurance"
    )


class UserProfileResponse(BaseModel):
    user_id: str
    full_name: str
    age: int | None = None
    height_cm: float | None = None
    fitness_goal: str | None = None


class BodyMetricCreate(BaseModel):
    weight_kg: float = Field(..., gt=0, description="Body weight in kilograms")
    body_fat_pct: float | None = Field(default=None, ge=0, le=100, description="Body fat percentage")
    muscle_mass_kg: float | None = Field(default=None, gt=0, description="Skeletal muscle mass in kg")


class BodyMetricResponse(BodyMetricCreate):
    metric_id: str
    user_id: str
    recorded_at: datetime
