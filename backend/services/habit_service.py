"""Business Logic Layer (Service) for Habits and Daily Check-ins."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from repositories.habit_repository import HabitRepository
from schemas.habit import (
    HabitCheckInCreate,
    HabitCheckInResponse,
    HabitCreate,
    HabitResponse,
)


class HabitService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = HabitRepository(db)

    async def create_habit(self, user_id: str, data: HabitCreate) -> HabitResponse:
        """Create a new daily habit for a user.

        TODO: Instantiate `Habit` ORM model and call `await self.repo.create_habit(habit)`.
        """
        return HabitResponse(
            habit_id=str(uuid4()),
            user_id=user_id,
            name=data.name,
            target_value=data.target_value,
            unit=data.unit,
            created_at=datetime.now(UTC),
        )

    async def list_habits(self, user_id: str) -> list[HabitResponse]:
        """List all habits for a user.

        TODO: Call `await self.repo.list_habits(user_id)`.
        """
        return []

    async def check_in_habit(
        self, user_id: str, habit_id: str, data: HabitCheckInCreate
    ) -> HabitCheckInResponse:
        """Record or update a daily check-in for a habit.

        TODO: Instantiate `HabitCheckIn` ORM model and call `await self.repo.upsert_checkin(checkin)`.
        """
        return HabitCheckInResponse(
            checkin_id=str(uuid4()),
            habit_id=habit_id,
            user_id=user_id,
            value=data.value,
            checkin_date=data.checkin_date or datetime.now(UTC).date(),
        )

    async def list_daily_checkins(
        self, user_id: str, target_date: date | None = None
    ) -> list[HabitCheckInResponse]:
        """List habit check-ins for a specific date.

        TODO: Call `await self.repo.list_checkins_by_date(user_id, resolved_date)`.
        """
        return []

