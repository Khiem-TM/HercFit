from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from fastapi import HTTPException, status as http_status
from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Select, String, Text, event, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from models.basemodel import BaseModel
from schemas.common import Pagination, UserScope, VersionCheck
from schemas.enums import GoalStatus
from schemas.goal import GoalCreate, GoalUpdate

if TYPE_CHECKING:
    from models.user import User


class Goal(BaseModel):
    # Dữ liệu Goal là linh động, không có schema cố định. Các trường dữ liệu được lưu trong cột JSONB.
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("title ~ '[^[:space:]]'", name="ck_goals_title"),
        CheckConstraint("jsonb_typeof(goal_types) = 'array'", name="ck_goals_types_array"),
        CheckConstraint("jsonb_typeof(targets) = 'object'", name="ck_goals_targets_object"),
        CheckConstraint("jsonb_typeof(context) = 'object'", name="ck_goals_context_object"),
        CheckConstraint("target_date IS NULL OR target_date >= start_date", name="ck_goals_dates"),
        Index("ix_goals_user_created", "user_id", "created_at", "id"),
        Index(
            "uq_goals_current_user", "user_id", unique=True,
            postgresql_where=text("is_active = true AND status = 'IN_PROGRESS'"),
        ),
    )

    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_types: Mapped[list[str]] = mapped_column(
        JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False,
    )
    # Đa số trường hợp người dung sẽ đặt mục tiêu giảm cân, tăng cơ, hoặc chạy bộ. Tuy nhiên, để linh hoạt hơn, chúng ta có thể cho phép người dùng tạo các loại mục tiêu khác nhau, ví dụ: "weight_loss", "muscle_gain", "running_distance", v.v.
    weight_kg_target: Mapped[float | None] = mapped_column(
        CheckConstraint("weight_kg_target IS NULL OR (weight_kg_target > 0 AND weight_kg_target < 1000)", name="ck_goals_weight_kg"),
        nullable=True,
    )
    # Xử lý khéo léo ở bên Frontend để người dùng có thể tạo các loại mục tiêu khác nhau, ví dụ: "weight_loss", "muscle_gain", "running_distance", v.v.
    targets: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus, name="goal_status", validate_strings=True),
        default=GoalStatus.IN_PROGRESS, server_default="IN_PROGRESS", nullable=False,
    )
    user: Mapped[User] = relationship("User", back_populates="goals")

    @classmethod
    def _user_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        user_id = UserScope(user_id=user_id).user_id
        return cls.apply_active_scope(
            select(cls).where(cls.user_id == user_id), include_inactive=include_inactive,
        )

    @classmethod
    async def _lock_user(cls, session: AsyncSession, user_id: PyUUID) -> bool:
        from models.user import User

        user_id = UserScope(user_id=user_id).user_id
        result = await session.execute(
            select(User.id).where(User.id == user_id, User.is_active.is_(True)).with_for_update()
        )
        return result.scalar_one_or_none() is not None

    @classmethod
    async def create_for_user(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: GoalCreate | Mapping[str, Any],
    ) -> Goal:
        values = GoalCreate.model_validate(payload).to_payload()
        if not await cls._lock_user(session, user_id):
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="User not found")
        if await cls.get_current_for_user(session, user_id=user_id) is not None:
            raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="User already has a current goal")
        return await cls.create(
            session, {**values, "user_id": user_id, "status": GoalStatus.IN_PROGRESS},
        )

    @classmethod
    async def update_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID,
        payload: GoalUpdate | Mapping[str, Any], expected_version_id: int,
    ) -> Goal | None:
        """Replace supplied fields; reject stale edits without committing caller work."""
        expected_version_id = VersionCheck(expected_version_id=expected_version_id).expected_version_id
        values = GoalUpdate.model_validate(payload).to_payload()
        async with session.begin_nested():
            if not await cls._lock_user(session, user_id):
                return None
            result = await session.execute(
                cls._user_query(user_id).where(cls.id == goal_id).with_for_update()
            )
            goal = result.scalar_one_or_none()
            if goal is None:
                return None
            await session.refresh(goal)
            if goal.status != GoalStatus.IN_PROGRESS:
                raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="Goal has already ended")
            if goal.version_id != expected_version_id:
                raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="Goal version has changed; reload before editing")
            # Validate dates against the stored counterpart when PATCH supplies only one.
            GoalCreate.model_validate({
                "title": goal.title, "start_date": goal.start_date,
                "target_date": goal.target_date, **values,
            })
            for key, value in values.items():
                setattr(goal, key, value)
            await session.flush()
            await session.refresh(goal)
        return goal

    @classmethod
    async def get_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ) -> Goal | None:
        result = await session.execute(
            cls._user_query(user_id, include_inactive=include_inactive).where(cls.id == goal_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_current_for_user(cls, session: AsyncSession, *, user_id: PyUUID) -> Goal | None:
        result = await session.execute(
            cls._user_query(user_id).where(cls.status == GoalStatus.IN_PROGRESS)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, *, user_id: PyUUID, offset: int = 0, limit: int = 50,
        include_inactive: bool = False,
    ) -> list[Goal]:
        options = Pagination(offset=offset, limit=limit, include_inactive=include_inactive)
        result = await session.execute(
            cls._user_query(user_id, include_inactive=options.include_inactive)
            .order_by(cls.created_at.desc(), cls.id.desc()).offset(options.offset).limit(options.limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def _finish_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID, target: GoalStatus,
    ) -> Goal | None:
        from models.plans import Plan

        async with session.begin_nested():
            if not await cls._lock_user(session, user_id):
                return None
            result = await session.execute(
                cls._user_query(user_id).where(cls.id == goal_id).with_for_update()
            )
            goal = result.scalar_one_or_none()
            if goal is None:
                return None
            # Refresh cached state after waiting for another transaction's User lock.
            await session.refresh(goal)
            if goal.status == target:
                return goal
            if goal.status != GoalStatus.IN_PROGRESS:
                raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="Goal has already ended")
            await Plan.end_for_goal(session, user_id=user_id, goal_id=goal.id, reason=f"GOAL_{target.value}")
            goal.status = target
            await session.flush()
            await session.refresh(goal)
        return goal

    @classmethod
    async def complete_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID,
    ) -> Goal | None:
        return await cls._finish_for_user(session, goal_id, user_id=user_id, target=GoalStatus.COMPLETED)

    @classmethod
    async def cancel_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID,
    ) -> Goal | None:
        return await cls._finish_for_user(session, goal_id, user_id=user_id, target=GoalStatus.CANCELLED)

    @classmethod
    async def soft_delete_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID,
    ) -> Goal | None:
        """Serialize with confirmation so deleting a current goal frees its slot."""
        from models.plans import Plan

        async with session.begin_nested():
            if not await cls._lock_user(session, user_id):
                return None
            result = await session.execute(
                cls._user_query(user_id, include_inactive=True).where(cls.id == goal_id)
                .with_for_update().execution_options(populate_existing=True)
            )
            goal = result.scalar_one_or_none()
            if goal is not None and goal.is_active:
                await Plan.end_for_goal(session, user_id=user_id, goal_id=goal.id, reason="GOAL_DELETED")
                goal.is_active = False
                await session.flush()
                await session.refresh(goal)
        return goal


@event.listens_for(Goal, "before_update")
def _protect_goal_owner(_mapper: Mapper, _connection: Connection, goal: Goal) -> None:
    state = inspect(goal)
    if state.attrs.user_id.history.has_changes():
        raise ValueError("Goal owner cannot be changed")
