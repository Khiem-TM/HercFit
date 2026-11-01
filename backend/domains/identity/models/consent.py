"""Những gì người dùng cho phép HercFit làm với dữ liệu sức khoẻ của họ, thành một bản ghi riêng.

user_consents giữ quyết định hiện tại theo (mục đích, nhóm dữ liệu); consent_events
là lịch sử chỉ-ghi-thêm. Cổng của knowledge graph (kg_device_consent) cũng đọc
user_consents, nên lệnh đọc SQL, tool và graph đều theo một quyết định.

`version` tăng ở mọi thay đổi của một người dùng (trên mọi mục đích và nhóm), để
job hay ngữ cảnh cache dựng theo phiên bản cũ hơn bị nhận ra là đã cũ.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base

PURPOSES = ("assistant",)
DATA_GROUPS = ("device", "sensitive")
ACTORS = ("USER", "SYSTEM", "MIGRATION")


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        CheckConstraint("purpose IN ('assistant')", name="ck_user_consents_purpose"),
        CheckConstraint("data_group IN ('device', 'sensitive')", name="ck_user_consents_data_group"),
        CheckConstraint("version >= 1", name="ck_user_consents_version"),
    )

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            primary_key=True)
    purpose: Mapped[str] = mapped_column(String(30), primary_key=True)
    data_group: Mapped[str] = mapped_column(String(30), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConsentEvent(Base):
    __tablename__ = "consent_events"
    __table_args__ = (
        CheckConstraint("actor IN ('USER', 'SYSTEM', 'MIGRATION')", name="ck_consent_events_actor"),
        Index("ix_consent_events_user", "user_id", "occurred_at"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                       server_default=text("gen_random_uuid()"))
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    data_group: Mapped[str] = mapped_column(String(30), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
