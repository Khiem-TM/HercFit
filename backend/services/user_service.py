"""Business Logic Layer (Service) for Users and Body Metrics."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from repositories.user_repository import UserRepository
from schemas.user import (
    BodyMetricCreate,
    BodyMetricResponse,
    UserProfileResponse,
    UserProfileUpdate,
)


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = UserRepository(db)

    async def get_user_profile(self, user_id: str) -> UserProfileResponse:
        """Fetch user profile and fitness goals.

        TODO: Call `await self.repo.get_by_id(user_id)` and return `UserProfileResponse.model_validate(user)`.
        """
        return UserProfileResponse(
            user_id=user_id,
            full_name="Health User",
            age=25,
            height_cm=172.0,
            fitness_goal="muscle_gain",
        )

    async def update_user_profile(
        self, user_id: str, data: UserProfileUpdate
    ) -> UserProfileResponse:
        """Update user profile information.

        TODO: Call `self.repo.get_by_id(user_id)` and `self.repo.update(user, update_dict)`.
        """
        profile = await self.get_user_profile(user_id)
        update_dict = data.model_dump(exclude_unset=True)
        return profile.model_copy(update=update_dict)

    async def log_body_metric(
        self, user_id: str, data: BodyMetricCreate
    ) -> BodyMetricResponse:
        """Record a new body metric entry (weight, body fat, muscle mass).

        TODO: Instantiate `BodyMetric` ORM model and call `await self.repo.create_body_metric(metric)`.
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
        self, user_id: str, limit: int = 10
    ) -> list[BodyMetricResponse]:
        """List recent body metric logs for a user.

        TODO: Call `await self.repo.list_body_metrics(user_id, limit=limit)`.
        """
        return []

