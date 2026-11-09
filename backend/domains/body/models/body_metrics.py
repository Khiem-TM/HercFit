from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domains.shared.models.basemodel import BaseModel, utc_now
from domains.shared.models.domain import guard_immutable
from domains.body.schemas.body_metrics import CIRCUMFERENCES, BodyMetricCreate, BodyMetricQuery
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
        *[
            CheckConstraint(f"{field} > 0 AND {field} < 400", name=f"ck_body_metrics_{field}")
            for field in CIRCUMFERENCES
        ],
        CheckConstraint("jsonb_typeof(additional_metrics) = 'object'", name="ck_body_metrics_additional_object"),
        # Mẫu từ thiết bị mỗi mẫu mang một số đo (cân nặng từ cân, một chỉ số mỡ cơ thể).
        CheckConstraint("weight_kg IS NOT NULL OR height_cm IS NOT NULL OR body_fat_pct IS NOT NULL "
                        "OR muscle_mass_kg IS NOT NULL OR chest_cm IS NOT NULL OR waist_cm IS NOT NULL "
                        "OR hip_cm IS NOT NULL", name="ck_body_metrics_any_measurement"),
        CheckConstraint("source IN ('MANUAL', 'GOOGLE_HEALTH')", name="ck_body_metrics_source"),
        Index("ix_body_metrics_user_recorded", "user_id", "recorded_at", "id"),
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
    # Vòng ngực / eo / hông (cm): Google Health không có, nên luôn lưu trong HercFit (migration 0030).
    chest_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    waist_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    hip_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    additional_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )
    # Dòng ở đây do người dùng hoặc trợ lý nhập (MANUAL). Cân nặng, chiều cao, mỡ cơ thể trên Google
    # nằm ở health_points và được gộp vào lúc đọc (domains/body/services/readings.py).
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", server_default="MANUAL", nullable=False)
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
        offset: int = 0, limit: int = 50, include_inactive: bool = False, respect_consent: bool = True,
    ) -> list[Any]:
        """Số đo nhập tay cùng mẫu cân nặng / chiều cao / mỡ từ Google, mới nhất trước.

        Mẫu Google chỉ hiện với trợ lý khi người dùng cho phép dùng dữ liệu thiết bị.
        """
        from domains.body.services import readings

        options = BodyMetricQuery(
            recorded_from=recorded_from, recorded_to=recorded_to,
            offset=offset, limit=limit, include_inactive=include_inactive,
        )
        query = cls._user_query(user_id, include_inactive=options.include_inactive)
        if options.recorded_from is not None:
            query = query.where(cls.recorded_at >= options.recorded_from)
        if options.recorded_to is not None:
            query = query.where(cls.recorded_at <= options.recorded_to)
        wanted = options.offset + options.limit
        local = list((await session.execute(
            query.order_by(cls.recorded_at.desc(), cls.id.desc()).limit(wanted))).scalars())
        google = await readings.google(session, user_id, options.recorded_from, options.recorded_to,
                                       limit=wanted, respect_consent=respect_consent)
        merged = sorted([*local, *google], key=lambda item: (item.recorded_at, str(item.id)), reverse=True)
        return merged[options.offset:wanted]

    @classmethod
    async def get_latest_for_user(cls, session: AsyncSession, *, user_id: PyUUID,
                                  respect_consent: bool = True) -> Any | None:
        """Lần cân gần nhất (nhập tay hoặc Google); mẫu chỉ có chiều cao hay mỡ không phải lần cân.

        `respect_consent=False` dành cho tính toán bên trong một lệnh ghi đã xác nhận (ví dụ
        cân nặng dùng cho ước tính calo của buổi tập), không bao giờ cho lần đọc hiển thị với ai.
        """
        return await cls.latest(session, user_id, "weight_kg", respect_consent=respect_consent)

    @classmethod
    async def latest(cls, session: AsyncSession, user_id: PyUUID, field: str, *,
                     respect_consent: bool = True) -> Any | None:
        """Số đo mới nhất có `field` (weight_kg, height_cm, body_fat_pct, vòng đo) từ cả hai nguồn."""
        from domains.body.services import readings

        local = (await session.execute(cls._user_query(user_id).where(getattr(cls, field).is_not(None))
                                       .order_by(cls.recorded_at.desc(), cls.id.desc()).limit(1))).scalar_one_or_none()
        if field not in readings.FIELDS:  # vòng đo, khối cơ: chỉ có trong HercFit
            return local
        google = await readings.google(session, user_id, limit=1, field=field, respect_consent=respect_consent)
        found = [item for item in (local, *google) if item is not None]
        return max(found, key=lambda item: item.recorded_at) if found else None

    @classmethod
    async def replace_for_user(
        cls, session: AsyncSession, metric_id: PyUUID, *, user_id: PyUUID,
        payload: BodyMetricCreate | Mapping[str, Any],
    ) -> BodyMetric | None:
        """Thay nguyên tử một ảnh chụp đang hoạt động bằng payload mới đầy đủ."""
        values = BodyMetricCreate.model_validate(payload).to_payload()
        async with session.begin_nested():
            result = await session.execute(
                cls._user_query(user_id).where(cls.id == metric_id).with_for_update()
            )
            original = result.scalar_one_or_none()
            if original is None:
                return None
            # Lần sửa giữ thời điểm đo trừ khi được truyền tường minh.
            replacement = await cls.create_snapshot(
                session, user_id=user_id,
                payload={"recorded_at": original.recorded_at, **values},
            )
            original.is_active = False
            await session.flush()
            await session.refresh(original)
        return replacement



guard_immutable(BodyMetric)
