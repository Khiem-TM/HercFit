"""Pydantic v2 DTO schemas for Habits and Daily Check-ins."""

from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field


class HabitCreate(BaseModel):
    name: str
    target_value: float = Field(..., gt=0)
    unit: str = Field(..., description="e.g. 'ml', 'hours', 'steps'")


class HabitResponse(HabitCreate):
    model_config = ConfigDict(from_attributes=True)

    habit_id: str
    user_id: str
    created_at: datetime


class HabitCheckInCreate(BaseModel):
    value: float = Field(..., ge=0)
    checkin_date: date | None = None


class HabitCheckInResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    checkin_id: str
    habit_id: str
    user_id: str
    value: float
    checkin_date: date

