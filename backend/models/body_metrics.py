"""Immutable measurement snapshots; scoped methods leave transactions to callers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Numeric, Select,
    event, func, inspect, select, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from models.basemodel import BaseModel, utc_now
from schemas.body_metrics import BodyMetricCreate, BodyMetricQuery
from schemas.common import UserScope

if TYPE_CHECKING:
    from models.user import User


class BodyMetric(BaseModel):
    __tablename__ = "body_metrics"
    __table_args__ = (
        *[
            CheckConstraint(f"{field} > 0 AND {field} < 10000000", name=f"ck_body_metrics_{field}")
            for field in ("weight_kg", "height_cm", "muscle_mass_kg")
        ],
        CheckConstraint("body_fat_pct >= 0 AND body_fat_pct <= 100", name="ck_body_metrics_body_fat"),
        CheckConstraint("jsonb_typeof(additional_metrics) = 'object'", name="ck_body_metrics_additional_object"),
        Index("ix_body_metrics_user_recorded", "user_id", "recorded_at", "id"),
    )

    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False,
    )
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    body_fat_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    muscle_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    additional_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )
    user: Mapped[User] = relationship("User", back_populates="body_metrics")

    @classmethod
    def _user_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        user_id = UserScope(user_id=user_id).user_id
        return cls.apply_active_scope(
            select(cls).where(cls.user_id == user_id), include_inactive=include_inactive,
        )

    @classmethod
    async def create_snapshot(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: BodyMetricCreate | Mapping[str, Any],
    ) -> BodyMetric:
        user_id = UserScope(user_id=user_id).user_id
        values = BodyMetricCreate.model_validate(payload).to_payload()
        return await cls.create(session, {**values, "user_id": user_id})

    @classmethod
    async def get_for_user(
        cls, session: AsyncSession, metric_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ) -> BodyMetric | None:
        result = await session.execute(
            cls._user_query(user_id, include_inactive=include_inactive).where(cls.id == metric_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, *, user_id: PyUUID,
        recorded_from: datetime | None = None, recorded_to: datetime | None = None,
        offset: int = 0, limit: int = 50, include_inactive: bool = False,
    ) -> list[BodyMetric]:
        options = BodyMetricQuery(
            recorded_from=recorded_from, recorded_to=recorded_to,
            offset=offset, limit=limit, include_inactive=include_inactive,
        )
        query = cls._user_query(user_id, include_inactive=options.include_inactive)
        if options.recorded_from is not None:
            query = query.where(cls.recorded_at >= options.recorded_from)
        if options.recorded_to is not None:
            query = query.where(cls.recorded_at <= options.recorded_to)
        result = await session.execute(
            query.order_by(cls.recorded_at.desc(), cls.id.desc()).offset(options.offset).limit(options.limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_latest_for_user(cls, session: AsyncSession, *, user_id: PyUUID) -> BodyMetric | None:
        records = await cls.list_for_user(session, user_id=user_id, limit=1)
        return cls.get_first_or_none(records)

    @classmethod
    async def soft_delete_for_user(
        cls, session: AsyncSession, metric_id: PyUUID, *, user_id: PyUUID,
    ) -> BodyMetric | None:
        result = await session.execute(
            cls._user_query(user_id, include_inactive=True).where(cls.id == metric_id).with_for_update()
        )
        metric = result.scalar_one_or_none()
        if metric is not None and metric.is_active:
            metric.is_active = False
            await session.flush()
            await session.refresh(metric)
        return metric

    @classmethod
    async def replace_for_user(
        cls, session: AsyncSession, metric_id: PyUUID, *, user_id: PyUUID,
        payload: BodyMetricCreate | Mapping[str, Any],
    ) -> BodyMetric | None:
        """Replace an active snapshot with a complete new payload, atomically."""
        values = BodyMetricCreate.model_validate(payload).to_payload()
        async with session.begin_nested():
            result = await session.execute(
                cls._user_query(user_id).where(cls.id == metric_id).with_for_update()
            )
            original = result.scalar_one_or_none()
            if original is None:
                return None
            # A correction keeps the measurement time unless explicitly supplied.
            replacement = await cls.create_snapshot(
                session, user_id=user_id,
                payload={"recorded_at": original.recorded_at, **values},
            )
            original.is_active = False
            await session.flush()
            await session.refresh(original)
        return replacement


@event.listens_for(BodyMetric, "before_update")
def _protect_snapshot(_mapper: Mapper, _connection: Connection, metric: BodyMetric) -> None:
    state = inspect(metric)
    fields = ("user_id", "recorded_at", "weight_kg", "height_cm", "body_fat_pct", "muscle_mass_kg", "additional_metrics")
    if any(state.attrs[field].history.has_changes() for field in fields):
        raise ValueError("Body metric snapshots are immutable; use replace_for_user")
