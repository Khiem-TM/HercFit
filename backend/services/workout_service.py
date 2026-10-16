"""Business Logic Layer (Service) for Workout Plans and Workout Sessions."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from repositories.workout_repository import WorkoutRepository
from schemas.workout import (
    WorkoutPlanCreate,
    WorkoutPlanResponse,
    WorkoutSessionCreate,
    WorkoutSessionResponse,
)


class WorkoutService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = WorkoutRepository(db)

    async def create_workout_plan(
        self, user_id: str, data: WorkoutPlanCreate
    ) -> WorkoutPlanResponse:
        """Create a workout plan for a user.

        TODO: Instantiate `WorkoutPlan` ORM model and call `await self.repo.create_plan(plan)`.
        """
        return WorkoutPlanResponse(
            plan_id=str(uuid4()),
            user_id=user_id,
            title=data.title,
            days_per_week=data.days_per_week,
            exercises=data.exercises,
            created_at=datetime.now(UTC),
        )

    async def list_workout_plans(self, user_id: str) -> list[WorkoutPlanResponse]:
        """List workout plans for a user.

        TODO: Call `await self.repo.list_plans(user_id)`.
        """
        return []

    async def log_workout_session(
        self, user_id: str, data: WorkoutSessionCreate
    ) -> WorkoutSessionResponse:
        """Log a completed workout session.

        TODO: Instantiate `WorkoutSession` ORM model and call `await self.repo.create_session(session_log)`.
        """
        return WorkoutSessionResponse(
            session_id=str(uuid4()),
            user_id=user_id,
            workout_name=data.workout_name,
            duration_minutes=data.duration_minutes,
            calories_burned=data.calories_burned,
            notes=data.notes,
            performed_at=datetime.now(UTC),
        )

    async def list_workout_sessions(
        self, user_id: str, limit: int = 10
    ) -> list[WorkoutSessionResponse]:
        """List recent workout sessions for a user.

        TODO: Call `await self.repo.list_sessions(user_id, limit=limit)`.
        """
        return []

