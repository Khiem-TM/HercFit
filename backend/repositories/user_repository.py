"""Data Access Layer (Repository) for Users and Body Metrics."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import BodyMetric, User
from repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession) -> None:
        super().__init__(db, User)

    async def get_by_id(self, user_id: str) -> User | None:
        """TODO: Query User by user_id using `select(User).where(User.user_id == user_id)`."""
        raise NotImplementedError

    async def update(self, user: User, update_data: dict[str, Any]) -> User:
        """TODO: Update fields on User ORM instance, flush, and refresh."""
        raise NotImplementedError

    async def create_body_metric(self, metric: BodyMetric) -> BodyMetric:
        """TODO: Add BodyMetric instance to session, flush, and refresh."""
        raise NotImplementedError

    async def list_body_metrics(self, user_id: str, limit: int = 10) -> list[BodyMetric]:
        """TODO: Query recent BodyMetric records for user_id ordered by recorded_at DESC."""
        raise NotImplementedError

