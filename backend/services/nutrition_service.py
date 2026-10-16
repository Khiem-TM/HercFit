"""Business Logic Layer (Service) for Nutrition and Meals."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from repositories.nutrition_repository import NutritionRepository
from schemas.nutrition import DailyNutritionSummary, MealCreate, MealResponse


class NutritionService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = NutritionRepository(db)

    async def log_meal(self, user_id: str, data: MealCreate) -> MealResponse:
        """Record a meal intake for a user.

        TODO: Instantiate `Meal` ORM model and call `await self.repo.create_meal(meal)`.
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
        self, user_id: str, target_date: date | None = None
    ) -> DailyNutritionSummary:
        """Calculate daily calorie and macro totals for a user.

        TODO: Call `await self.repo.list_meals_by_date(user_id, resolved_date)` and aggregate macros.
        """
        resolved_date = target_date or datetime.now(UTC).date()
        return DailyNutritionSummary(
            user_id=user_id,
            target_date=resolved_date,
            total_calories=0,
            total_protein_g=0.0,
            total_carbs_g=0.0,
            total_fat_g=0.0,
            meals=[],
        )

