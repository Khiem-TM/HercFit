"""Dữ liệu sức khoẻ từ thiết bị đeo, đồng bộ từ Google Health API.

Tách ra từ models.health trong đợt tổ chức lại theo miền."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID as PyUUID
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from domains.shared.models.basemodel import BaseModel
from domains.health_records.schemas.health import HEALTH_PROVIDER
from domains.health_records.models.device_records import _json, _user_fk


class HealthConnection(BaseModel):
    __tablename__ = "health_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_health_connections_user_provider"),
        CheckConstraint("status IN ('ACTIVE', 'NEEDS_REAUTH', 'REVOKED', 'ERROR')", name="ck_health_connections_status"),
        CheckConstraint("jsonb_typeof(granted_scopes) = 'array'", name="ck_health_connections_scopes"),
        CheckConstraint("jsonb_typeof(provider_profile) = 'object'", name="ck_health_connections_profile"),
        CheckConstraint("jsonb_typeof(sync_cursor) = 'object'", name="ck_health_connections_cursor"),
        CheckConstraint("api_version IN ('v4', 'v4beta')", name="ck_health_connections_api_version"),
        Index("ix_health_connections_due", "next_sync_at", postgresql_where=text("status = 'ACTIVE'")),
        Index("uq_health_connections_health_user", "provider", "health_user_id", unique=True,
              postgresql_where=text("health_user_id IS NOT NULL")),
    )

    user_id: Mapped[PyUUID] = _user_fk()
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
    provider_profile: Mapped[dict[str, Any]] = _json()
    sync_cursor: Mapped[dict[str, Any]] = _json()
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # healthUserId của users.getIdentity: webhook định danh người dùng bằng nó, không bao giờ bằng OAuth subject.
    health_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Tăng ở mỗi lần (kết nối lại) và ngắt kết nối: job bắt đầu dưới thế hệ
    # cũ hơn không được ghi, gọi Google hay phục vụ ngữ cảnh nữa.
    generation: Mapped[int] = mapped_column(BigInteger, default=1, server_default=text("1"), nullable=False)
    # Fencing token: mỗi lần lấy lease tăng nó; lệnh ghi kiểm tra nó trong cùng transaction.
    lease_epoch: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"), nullable=False)
    api_version: Mapped[str] = mapped_column(String(8), default="v4", server_default="v4", nullable=False)

    @classmethod
    async def for_user(cls, session: AsyncSession, user_id: PyUUID, *, for_update: bool = False) -> HealthConnection | None:
        query = cls._user_query(user_id, include_inactive=True).where(cls.provider == HEALTH_PROVIDER)
        if for_update:
            query = query.with_for_update()
        return (await session.execute(query)).scalar_one_or_none()

class HealthSyncRun(BaseModel):
    __tablename__ = "health_sync_runs"
    __table_args__ = (
        CheckConstraint("trigger IN ('INITIAL', 'SCHEDULED', 'MANUAL')", name="ck_health_sync_runs_trigger"),
        CheckConstraint("status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')", name="ck_health_sync_runs_status"),
        CheckConstraint("jsonb_typeof(counts) = 'object'", name="ck_health_sync_runs_counts"),
        Index("ix_health_sync_runs_user_created", "user_id", "created_at"),
    )

    connection_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("health_connections.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[PyUUID] = _user_fk()
    trigger: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="RUNNING", server_default="RUNNING", nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    counts: Mapped[dict[str, Any]] = _json()
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
