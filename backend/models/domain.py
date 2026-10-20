"""Small persistence helpers shared by user-owned aggregate models."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.common import UserScope, VersionCheck


async def lock_user(session: AsyncSession, user_id: UUID):
    from models.user import User

    user_id = UserScope(user_id=user_id).user_id
    await session.flush()
    result = await session.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
        .with_for_update().execution_options(populate_existing=True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")
    return user


def require_version(entity, expected_version_id: int) -> None:
    expected = VersionCheck(expected_version_id=expected_version_id).expected_version_id
    if entity.version_id != expected:
        raise HTTPException(409, "Version has changed; reload before editing")


def guard_immutable(cls, allowed=()) -> None:
    """ORM safeguard; callers correct historical aggregates by replacing them."""
    allowed = set(allowed) | {"is_active", "updated_at", "version_id"}

    def protect(_mapper, _connection, entity):
        state = inspect(entity)
        if any(state.attrs[column.key].history.has_changes()
               for column in state.mapper.column_attrs if column.key not in allowed):
            raise ValueError(f"{cls.__name__} snapshots are immutable; replace the aggregate")

    event.listen(cls, "before_update", protect)
