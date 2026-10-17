"""Combined body, health and performance goals with optional numeric targets.

Use scoped methods for account-facing writes; inherited CRUD is internal only.
JSON fields are replaced as a whole, not merged or tracked through nested edits.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from enum import StrEnum
import json
import math
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from fastapi import HTTPException, status as http_status
from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Select, String, Text, event, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship, validates

from models.basemodel import BaseModel

if TYPE_CHECKING:
    from models.user import User


class GoalStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


def _validate_json(value: Any, expected_type: type, field: str) -> Any:
    if not isinstance(value, expected_type):
        raise ValueError(f"{field} must be a JSON {'array' if expected_type is list else 'object'}")
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must contain JSON-serializable, finite values") from None
    return deepcopy(value)


def _validate_target_number(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must be a finite JSON number")


def _validate_content(key: str, value: Any) -> Any:
    if key == "title":
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise ValueError("title must be a non-blank string of at most 255 characters")
    elif key == "description":
        if value is not None and not isinstance(value, str):
            raise ValueError("description must be a string or None")
    elif key == "goal_types":
        value = _validate_json(value, list, key)
        if any(not isinstance(label, str) or not label.strip() for label in value):
            raise ValueError("goal_types must contain non-blank string labels")
    elif key == "context":
        value = _validate_json(value, dict, key)
    elif key == "targets":
        value = _validate_json(value, dict, key)
        for code, target in value.items():
            if not isinstance(code, str) or not code.strip() or not isinstance(target, dict):
                raise ValueError("Each target needs a non-blank metric code and an object")
            unit = target.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                raise ValueError(f"targets.{code}.unit is required")
            operator = target.get("operator")
            if not isinstance(operator, str) or operator not in {"eq", "gte", "lte", "range"}:
                raise ValueError(f"targets.{code}.operator must be eq, gte, lte or range")
            numeric_fields = {"min", "max"} if operator == "range" else {"value"}
            allowed = {"unit", "operator", "baseline"} | numeric_fields
            if set(target) - allowed:
                raise ValueError(f"targets.{code} contains unsupported fields for {operator}")
            for field in numeric_fields | ({"baseline"} if "baseline" in target else set()):
                _validate_target_number(target.get(field), f"targets.{code}.{field}")
            if operator == "range" and target["min"] > target["max"]:
                raise ValueError(f"targets.{code}.min must not exceed max")
    return value


class Goal(BaseModel):
    """goal_types uses open labels, e.g. WEIGHT_LOSS, WEIGHT_GAIN, MUSCLE_GAIN,
    BODY_RECOMPOSITION, SPORT_PERFORMANCE, RECOVERY, MAINTENANCE, GENERAL_HEALTH.
    Targets may be empty; description/context preserve qualitative user intent.
    """
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

    @validates("title", "description", "goal_types", "targets", "context")
    def _validate_content(self, key: str, value: Any) -> Any:
        return _validate_content(key, value)

    @classmethod
    def _goal_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("Goal payload must be an object")
        if {"start_weight_kg", "target_weight_kg"}.intersection(payload):
            raise ValueError("Legacy weight fields are no longer supported; use targets.weight_kg")
        allowed = {"title", "description", "goal_types", "targets", "context", "start_date", "target_date"}
        # Validate the complete patch before changing any persistent attributes.
        return {key: _validate_content(key, value) for key, value in payload.items() if key in allowed}

    @classmethod
    def _user_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        if user_id is None:
            raise ValueError("user_id is required")
        return cls.apply_active_scope(
            select(cls).where(cls.user_id == user_id), include_inactive=include_inactive,
        )

    @classmethod
    async def _lock_user(cls, session: AsyncSession, user_id: PyUUID) -> bool:
        from models.user import User

        if user_id is None:
            raise ValueError("user_id is required")
        result = await session.execute(
            select(User.id).where(User.id == user_id, User.is_active.is_(True)).with_for_update()
        )
        return result.scalar_one_or_none() is not None

    @classmethod
    async def create_for_user(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: Mapping[str, Any],
    ) -> Goal:
        values = cls._goal_payload(payload)
        if "title" not in values or values.get("start_date") is None:
            raise ValueError("title and start_date are required")
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
        payload: Mapping[str, Any], expected_version_id: int,
    ) -> Goal | None:
        """Replace supplied fields; reject stale edits without committing caller work."""
        if type(expected_version_id) is not int or expected_version_id < 1:
            raise ValueError("expected_version_id must be a positive integer")
        values = cls._goal_payload(payload)
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
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit must be between 1 and 200; offset must be non-negative")
        result = await session.execute(
            cls._user_query(user_id, include_inactive=include_inactive)
            .order_by(cls.created_at.desc(), cls.id.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def _finish_for_user(
        cls, session: AsyncSession, goal_id: PyUUID, *, user_id: PyUUID, target: GoalStatus,
    ) -> Goal | None:
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


@event.listens_for(Goal, "before_update")
def _protect_goal_owner(_mapper: Mapper, _connection: Connection, goal: Goal) -> None:
    state = inspect(goal)
    if state.attrs.user_id.history.has_changes():
        raise ValueError("Goal owner cannot be changed")
