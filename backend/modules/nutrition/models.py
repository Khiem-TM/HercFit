"""Database models/table definitions for Nutrition and Meals."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MealRecord:
    meal_id: str
    user_id: str
    name: str
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    logged_at: datetime
