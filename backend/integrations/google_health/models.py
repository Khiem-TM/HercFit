"""Kết nối Google Health của người dùng và ánh xạ bản ghi HercFit đã đẩy lên Google."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from domains.health_records.schemas.health import HEALTH_PROVIDER
from domains.shared.models.basemodel import BaseModel


def _json():
    return mapped_column(JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False)


class HealthConnection(BaseModel):
    __tablename__ = "health_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_health_connections_user_provider"),
        CheckConstraint("status IN ('ACTIVE', 'NEEDS_REAUTH', 'REVOKED', 'ERROR')", name="ck_health_connections_status"),
        CheckConstraint("jsonb_typeof(granted_scopes) = 'array'", name="ck_health_connections_scopes"),
        CheckConstraint("jsonb_typeof(provider_profile) = 'object'", name="ck_health_connections_profile"),
        CheckConstraint("jsonb_typeof(sync_cursor) = 'object'", name="ck_health_connections_cursor"),
        CheckConstraint("jsonb_typeof(sync_groups) = 'object'", name="ck_health_connections_sync_groups"),
        CheckConstraint("sync_frequency IN ('hourly', 'open', 'manual')", name="ck_health_connections_sync_frequency"),
    )

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    provider: Mapped[str] = mapped_column(String(30), default=HEALTH_PROVIDER, server_default=HEALTH_PROVIDER, nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    granted_scopes: Mapped[list[str]] = mapped_column(
        JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", server_default="ACTIVE", nullable=False)
    share_with_assistant: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Do Google báo (users.getProfile / getSettings): tuổi, chiều dài sải chân, đơn vị.
    provider_profile: Mapped[dict[str, Any]] = _json()
    # Trạng thái đọc theo từng loại: {data_type: {"through": "YYYY-MM-DD", "error": code | null}}.
    sync_cursor: Mapped[dict[str, Any]] = _json()
    # Nhóm người dùng tắt đồng bộ ({"hrv": false}) và tần suất đồng bộ nền (migration 0030).
    sync_groups: Mapped[dict[str, bool]] = _json()
    sync_frequency: Mapped[str] = mapped_column(String(10), default="hourly", server_default="hourly", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @classmethod
    async def for_user(cls, session: AsyncSession, user_id: PyUUID, *, for_update: bool = False) -> HealthConnection | None:
        query = cls._user_query(user_id, include_inactive=True).where(cls.provider == HEALTH_PROVIDER)
        if for_update:
            query = query.with_for_update()
        return (await session.execute(query)).scalar_one_or_none()


class GooglePush(Base):
    """Một buổi gym hoặc bữa ăn HercFit đã đẩy lên Google và tên các data point tương ứng.

    `owned=false`: buổi gym được gắn vào phiên mà đồng hồ đã ghi, HercFit không tạo và không xoá nó.
    `pushed_at IS NULL`: cần đẩy (lại); bản ghi đã bị thay hoặc xoá mà còn `names` thì cần xoá trên Google.
    """
    __tablename__ = "google_pushes"
    __table_args__ = (CheckConstraint("record_type IN ('Training', 'Meal')", name="ck_google_pushes_type"),)

    record_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    record_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False, index=True)
    names: Mapped[list[str]] = mapped_column(ARRAY(String(300)), nullable=False, server_default=text("'{}'"))
    owned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(120), nullable=True)
