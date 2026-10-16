"""Pydantic schemas for Nutrition and Meal tracking."""

from datetime import date, datetime
from pydantic import BaseModel, Field


class MealCreate(BaseModel):
    name: str
    calories: int = Field(..., ge=0)
    protein_g: float = Field(default=0.0, ge=0.0)
    carbs_g: float = Field(default=0.0, ge=0.0)
    fat_g: float = Field(default=0.0, ge=0.0)


class MealResponse(MealCreate):
    meal_id: str
    user_id: str
    logged_at: datetime


class DailyNutritionSummary(BaseModel):
    user_id: str
    target_date: date
    total_calories: int
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float
    meals: list[MealResponse] = Field(default_factory=list)
