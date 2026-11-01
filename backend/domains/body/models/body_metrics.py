from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domains.shared.models.basemodel import BaseModel, utc_now
from domains.shared.models.domain import guard_immutable
from domains.body.schemas.body_metrics import BodyMetricCreate, BodyMetricQuery
from domains.shared.schemas.common import UserScope

if TYPE_CHECKING:
    from domains.identity.models.user import User


class BodyMetric(BaseModel):
    __tablename__ = "body_metrics"
    __table_args__ = (
        *[
            CheckConstraint(f"{field} > 0 AND {field} < 10000000", name=f"ck_body_metrics_{field}")
            for field in ("weight_kg", "height_cm", "muscle_mass_kg")
        ],
        CheckConstraint("body_fat_pct >= 0 AND body_fat_pct <= 100", name="ck_body_metrics_body_fat"),
        CheckConstraint("jsonb_typeof(additional_metrics) = 'object'", name="ck_body_metrics_additional_object"),
        # Device samples carry one measurement each (a scale weight, a body-fat reading).
        CheckConstraint("weight_kg IS NOT NULL OR height_cm IS NOT NULL OR body_fat_pct IS NOT NULL "
                        "OR muscle_mass_kg IS NOT NULL", name="ck_body_metrics_any_measurement"),
        CheckConstraint("source IN ('MANUAL', 'GOOGLE_HEALTH')", name="ck_body_metrics_source"),
        CheckConstraint("jsonb_typeof(data_source) = 'object'", name="ck_body_metrics_data_source"),
        Index("ix_body_metrics_user_recorded", "user_id", "recorded_at", "id"),
        Index("uq_body_metrics_external", "user_id", "source", "external_id", unique=True,
              postgresql_where=text("external_id IS NOT NULL AND is_active")),
    )

    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False,
    )
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    body_fat_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    muscle_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    additional_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )
    # MANUAL entries come from the user or the assistant; GOOGLE_HEALTH rows are
    # keyed by the provider's data point name so repeated syncs never duplicate.
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", server_default="MANUAL", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data_source: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )
    utc_offset_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_record_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("health_source_records.id", ondelete="SET NULL"), nullable=True)
    user: Mapped[User] = relationship("User", back_populates="body_metrics")

    @classmethod
    async def create_snapshot(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: BodyMetricCreate | Mapping[str, Any],
    ) -> BodyMetric:
        user_id = UserScope(user_id=user_id).user_id
        values = BodyMetricCreate.model_validate(payload).to_payload()
        return await cls.create(session, {**values, "user_id": user_id})

    @classmethod
    async def _visible(cls, session: AsyncSession, user_id: PyUUID, respect_consent: bool):
        """Device-measured rows are hidden from the assistant without the user's consent."""
        query = cls._user_query(user_id)
        if respect_consent:
            from domains.identity.consent import device_access

            if not await device_access(session, user_id):
                query = query.where(cls.source == "MANUAL")
        return query

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, *, user_id: PyUUID,
        recorded_from: datetime | None = None, recorded_to: datetime | None = None,
        offset: int = 0, limit: int = 50, include_inactive: bool = False, respect_consent: bool = True,
    ) -> list[BodyMetric]:
        options = BodyMetricQuery(
            recorded_from=recorded_from, recorded_to=recorded_to,
            offset=offset, limit=limit, include_inactive=include_inactive,
        )
        query = cls._user_query(user_id, include_inactive=options.include_inactive)
        if respect_consent:
            from domains.identity.consent import device_access

            if not await device_access(session, user_id):
                query = query.where(cls.source == "MANUAL")
        if options.recorded_from is not None:
            query = query.where(cls.recorded_at >= options.recorded_from)
        if options.recorded_to is not None:
            query = query.where(cls.recorded_at <= options.recorded_to)
        result = await session.execute(
            query.order_by(cls.recorded_at.desc(), cls.id.desc()).offset(options.offset).limit(options.limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def get_latest_for_user(cls, session: AsyncSession, *, user_id: PyUUID,
                                  respect_consent: bool = True) -> BodyMetric | None:
        """Latest weigh-in: device rows holding only height or body fat are not a weight.

        `respect_consent=False` is for computations inside a confirmed write (e.g. the
        bodyweight behind a training's calorie estimate), never for reads shown to anyone.
        """
        result = await session.execute(
            (await cls._visible(session, user_id, respect_consent)).where(cls.weight_kg.is_not(None))
            .order_by(cls.recorded_at.desc(), cls.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def sync_device_samples(
        cls, session: AsyncSession, *, user_id: PyUUID, source: str, rows: list[dict[str, Any]],
        window: tuple[datetime, datetime] | None = None,
    ) -> dict[str, int]:
        """Mirror provider samples. Snapshots stay immutable: a changed sample replaces
        the old row, and samples the provider no longer returns inside the synced
        window are deactivated. Returns inserted/replaced/removed counts."""
        fields = ("recorded_at", "weight_kg", "height_cm", "body_fat_pct", "muscle_mass_kg")
        incoming = {row["external_id"]: row for row in rows}
        query = cls._user_query(user_id).where(cls.source == source, cls.external_id.is_not(None))
        if window is not None:
            query = query.where(cls.recorded_at >= window[0], cls.recorded_at < window[1])
        if incoming and window is None:
            query = query.where(cls.external_id.in_(incoming))
        existing = {row.external_id: row for row in (await session.execute(query)).scalars()}
        if window is not None and incoming:
            outside = set(incoming) - set(existing)
            if outside:
                existing.update({row.external_id: row for row in (await session.execute(
                    cls._user_query(user_id).where(cls.source == source, cls.external_id.in_(outside))
                )).scalars()})
        counts = {"inserted": 0, "replaced": 0, "removed": 0}
        for external_id, row in incoming.items():
            current = existing.get(external_id)
            if current is not None and all(_same(getattr(current, f), row.get(f)) for f in fields):
                continue
            if current is not None:
                current.is_active = False
                await session.flush()
                counts["replaced"] += 1
            else:
                counts["inserted"] += 1
            session.add(cls(user_id=user_id, source=source, **row))
        for external_id, current in existing.items():
            if external_id not in incoming and window is not None and window[0] <= current.recorded_at < window[1]:
                current.is_active = False
                counts["removed"] += 1
        await session.flush()
        return counts

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


def _same(stored: Any, incoming: Any) -> bool:
    if stored is None or incoming is None:
        return stored is None and incoming is None
    if isinstance(stored, datetime):
        return stored == incoming
    return Decimal(str(stored)) == Decimal(str(incoming))


guard_immutable(BodyMetric)
