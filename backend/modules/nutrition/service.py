"""Business logic service for Nutrition (shared by CRUD API and Nutrition Agent tools)."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from modules.nutrition.schemas import DailyNutritionSummary, MealCreate, MealResponse


async def log_meal(db: Any, user_id: str, data: MealCreate) -> MealResponse:
    """Record a meal intake for a user.

    TODO: Replace stub with PostgreSQL INSERT into `meals` table.
    """
    return MealResponse(
        meal_id=str(uuid4()),
        user_id=user_id,
        name=data.name,
        calories=data.calories,
        protein_g=data.protein_g,
        carbs_g=data.carbs_g,
        fat_g=data.fat_g,
        logged_at=datetime.now(UTC),
    )


async def get_daily_nutrition_summary(
    db: Any, user_id: str, target_date: date | None = None
) -> DailyNutritionSummary:
    """Calculate daily calorie and macro totals for a user.

    TODO: Replace stub with PostgreSQL aggregation query on `meals` table.
    """
    return DailyNutritionSummary(
        user_id=user_id,
        target_date=target_date or datetime.now(UTC).date(),
        total_calories=0,
        total_protein_g=0.0,
        total_carbs_g=0.0,
        total_fat_g=0.0,
        meals=[],
    )
