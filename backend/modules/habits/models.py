"""Database models/table definitions for Habits and Daily Check-ins."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class HabitRecord:
    habit_id: str
    user_id: str
    name: str
    target_value: float
    unit: str
    created_at: datetime


@dataclass
class HabitCheckInRecord:
    checkin_id: str
    habit_id: str
    user_id: str
    value: float
    checkin_date: date
