"""Data Access Layer (Repository) for Nutrition and Meals."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from models.nutrition import Meal
from repositories.base import BaseRepository


class NutritionRepository(BaseRepository[Meal]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db, Meal)

    async def create_meal(self, meal: Meal) -> Meal:
        """TODO: Add Meal instance to session, flush, and refresh."""
        raise NotImplementedError

    async def list_meals_by_date(self, user_id: str, target_date: date) -> list[Meal]:
        """TODO: Query Meal records for user_id on target_date ordered by logged_at DESC."""
        raise NotImplementedError

    async def delete_meal(self, user_id: str, meal_id: str) -> bool:
        """TODO: Delete Meal record belonging to user_id."""
        raise NotImplementedError

