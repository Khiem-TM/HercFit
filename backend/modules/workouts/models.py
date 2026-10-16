"""Database models/table definitions for Workouts."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class WorkoutPlanRecord:
    plan_id: str
    user_id: str
    title: str
    days_per_week: int
    created_at: datetime


@dataclass
class WorkoutSessionRecord:
    session_id: str
    user_id: str
    workout_name: str
    duration_minutes: int
    calories_burned: int | None
    performed_at: datetime
