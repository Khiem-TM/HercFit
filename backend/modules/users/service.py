"""Business logic service for Users and Body Metrics (shared by CRUD API and AI Agent tools)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from modules.users.schemas import (
    BodyMetricCreate,
    BodyMetricResponse,
    UserProfileResponse,
    UserProfileUpdate,
)


async def get_user_profile(db: Any, user_id: str) -> UserProfileResponse:
    """Fetch user profile and fitness goals.

    TODO: Replace stub with PostgreSQL query against `users` table.
    """
    return UserProfileResponse(
        user_id=user_id,
        full_name="Health User",
        age=25,
        height_cm=172.0,
        fitness_goal="muscle_gain",
    )


async def update_user_profile(
    db: Any, user_id: str, data: UserProfileUpdate
) -> UserProfileResponse:
    """Update user profile information.

    TODO: Replace stub with PostgreSQL UPDATE query.
    """
    profile = await get_user_profile(db, user_id)
    update_dict = data.model_dump(exclude_unset=True)
    return profile.model_copy(update=update_dict)


async def log_body_metric(
    db: Any, user_id: str, data: BodyMetricCreate
) -> BodyMetricResponse:
    """Record a new body metric entry (weight, body fat, muscle mass).

    TODO: Replace stub with PostgreSQL INSERT into `body_metrics` table.
    """
    return BodyMetricResponse(
        metric_id=str(uuid4()),
        user_id=user_id,
        weight_kg=data.weight_kg,
        body_fat_pct=data.body_fat_pct,
        muscle_mass_kg=data.muscle_mass_kg,
        recorded_at=datetime.now(UTC),
    )


async def list_body_metrics(
    db: Any, user_id: str, limit: int = 10
) -> list[BodyMetricResponse]:
    """List recent body metric logs for a user.

    TODO: Replace stub with PostgreSQL SELECT from `body_metrics` table.
    """
    return []
