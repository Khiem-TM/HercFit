from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Numeric, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.basemodel import BaseModel, utc_now
from models.domain import guard_immutable
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
    async def create_snapshot(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: BodyMetricCreate | Mapping[str, Any],
    ) -> BodyMetric:
        user_id = UserScope(user_id=user_id).user_id
        values = BodyMetricCreate.model_validate(payload).to_payload()
        return await cls.create(session, {**values, "user_id": user_id})

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
        return await cls.get_one(
            session, user_id=UserScope(user_id=user_id).user_id,
            order_by={"recorded_at": "desc", "id": "desc"},
        )

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


guard_immutable(BodyMetric)
