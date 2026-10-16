"""Data Access Layer (Repository) for Habits and Daily Check-ins."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from models.habit import Habit, HabitCheckIn
from repositories.base import BaseRepository


class HabitRepository(BaseRepository[Habit]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db, Habit)

    async def create_habit(self, habit: Habit) -> Habit:
        """TODO: Add Habit instance to session, flush, and refresh."""
        raise NotImplementedError

    async def list_habits(self, user_id: str) -> list[Habit]:
        """TODO: Query Habit records for user_id ordered by created_at ASC."""
        raise NotImplementedError

    async def upsert_checkin(self, checkin: HabitCheckIn) -> HabitCheckIn:
        """TODO: Insert or update HabitCheckIn on (habit_id, checkin_date) conflict."""
        raise NotImplementedError

    async def list_checkins_by_date(
        self, user_id: str, target_date: date
    ) -> list[HabitCheckIn]:
        """TODO: Query HabitCheckIn records for user_id on target_date."""
        raise NotImplementedError

