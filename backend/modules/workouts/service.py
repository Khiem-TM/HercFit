"""Business logic service for Workouts (shared by CRUD API and Workout Agent tools)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from modules.workouts.schemas import (
    WorkoutPlanCreate,
    WorkoutPlanResponse,
    WorkoutSessionCreate,
    WorkoutSessionResponse,
)


async def create_workout_plan(
    db: Any, user_id: str, data: WorkoutPlanCreate
) -> WorkoutPlanResponse:
    """Create a workout plan for a user.

    TODO: Replace stub with PostgreSQL INSERT into `workout_plans` table.
    """
    return WorkoutPlanResponse(
        plan_id=str(uuid4()),
        user_id=user_id,
        title=data.title,
        days_per_week=data.days_per_week,
        exercises=data.exercises,
        created_at=datetime.now(UTC),
    )


async def list_workout_plans(db: Any, user_id: str) -> list[WorkoutPlanResponse]:
    """List workout plans for a user.

    TODO: Replace stub with PostgreSQL SELECT from `workout_plans` table.
    """
    return []


async def log_workout_session(
    db: Any, user_id: str, data: WorkoutSessionCreate
) -> WorkoutSessionResponse:
    """Log a completed workout session.

    TODO: Replace stub with PostgreSQL INSERT into `workout_sessions` table.
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
    db: Any, user_id: str, limit: int = 10
) -> list[WorkoutSessionResponse]:
    """List recent workout sessions for a user.

    TODO: Replace stub with PostgreSQL SELECT from `workout_sessions` table.
    """
    return []
