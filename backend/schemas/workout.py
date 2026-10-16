"""Pydantic v2 DTO schemas for Workout Plans and Workout Session logs."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ExerciseItem(BaseModel):
    name: str
    sets: int = Field(..., ge=1)
    reps: str = Field(..., description="e.g. '8-12' or '10'")
    rest_seconds: int = Field(default=60, ge=0)


class WorkoutPlanCreate(BaseModel):
    title: str
    days_per_week: int = Field(..., ge=1, le=7)
    exercises: list[ExerciseItem] = Field(default_factory=list)


class WorkoutPlanResponse(WorkoutPlanCreate):
    model_config = ConfigDict(from_attributes=True)

    plan_id: str
    user_id: str
    created_at: datetime


class WorkoutSessionCreate(BaseModel):
    workout_name: str
    duration_minutes: int = Field(..., gt=0)
    calories_burned: int | None = Field(default=None, ge=0)
    notes: str | None = None


class WorkoutSessionResponse(WorkoutSessionCreate):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    user_id: str
    performed_at: datetime

