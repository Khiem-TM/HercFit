"""Data Access Layer (Repository) for Workout Plans and Workout Sessions."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.workout import WorkoutPlan, WorkoutSession
from repositories.base import BaseRepository


class WorkoutRepository(BaseRepository[WorkoutPlan]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db, WorkoutPlan)

    async def create_plan(self, plan: WorkoutPlan) -> WorkoutPlan:
        """TODO: Add WorkoutPlan instance to session, flush, and refresh."""
        raise NotImplementedError

    async def list_plans(self, user_id: str) -> list[WorkoutPlan]:
        """TODO: Query WorkoutPlan records for user_id ordered by created_at DESC."""
        raise NotImplementedError

    async def create_session(self, session_log: WorkoutSession) -> WorkoutSession:
        """TODO: Add WorkoutSession instance to session, flush, and refresh."""
        raise NotImplementedError

    async def list_sessions(self, user_id: str, limit: int = 10) -> list[WorkoutSession]:
        """TODO: Query recent WorkoutSession records for user_id ordered by performed_at DESC."""
        raise NotImplementedError

