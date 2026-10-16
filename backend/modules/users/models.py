"""Database models/table definitions for Users and Body Metrics."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserRecord:
    user_id: str
    full_name: str
    age: int | None = None
    height_cm: float | None = None
    fitness_goal: str | None = None


@dataclass
class BodyMetricRecord:
    metric_id: str
    user_id: str
    weight_kg: float
    body_fat_pct: float | None
    muscle_mass_kg: float | None
    recorded_at: datetime
