"""Bảng `user_notifications`: hộp thư trong ứng dụng, một dòng một thông báo (migration 0029; loại mới ở 0030, 0031)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from domains.shared.models.basemodel import uuid7

KINDS = ("briefing", "insight", "praise", "data_quality", "reminder", "summary", "proposal", "alert", "review")


class UserNotification(Base):
    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_user_notifications_dedup"),
        Index("ix_user_notifications_user_created", "user_id", "created_at"),
        CheckConstraint("kind IN ('briefing', 'insight', 'praise', 'data_quality', 'reminder', 'summary', 'proposal', "
                        "'alert', 'review')",
                        name="user_notifications_kind_check"),
        CheckConstraint("priority BETWEEN 1 AND 3", name="user_notifications_priority_check"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("2"))
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    async def insert_unique(cls, session, row: dict[str, Any]) -> PyUUID | None:
        """Chèn nếu dedup_key chưa có; trả id mới, hoặc None khi một tiến trình khác đã tạo."""
        statement = (insert(cls).values(id=uuid7(), **row)
                     .on_conflict_do_nothing(constraint="uq_user_notifications_dedup").returning(cls.id))
        return (await session.execute(statement)).scalar_one_or_none()

    @classmethod
    def _visible(cls, user_id: PyUUID, now: datetime):
        return (cls.user_id == user_id, cls.dismissed_at.is_(None),
                or_(cls.expires_at.is_(None), cls.expires_at > now))

    @classmethod
    async def list_for(cls, session, user_id: PyUUID, *, now: datetime, unread_only: bool = False,
                       limit: int = 20) -> list[UserNotification]:
        query = select(cls).where(*cls._visible(user_id, now))
        if unread_only:
            query = query.where(cls.seen_at.is_(None))
        return list((await session.execute(query.order_by(cls.created_at.desc()).limit(limit))).scalars())

    @classmethod
    async def unread_count(cls, session, user_id: PyUUID, *, now: datetime) -> int:
        query = select(func.count()).select_from(cls).where(*cls._visible(user_id, now), cls.seen_at.is_(None))
        return int((await session.execute(query)).scalar_one())

    @classmethod
    async def count_for_day(cls, session, user_id: PyUUID, day: date) -> int:
        query = select(func.count()).select_from(cls).where(cls.user_id == user_id, cls.local_date == day)
        return int((await session.execute(query)).scalar_one())

    @classmethod
    async def keys(cls, session, user_id: PyUUID, dedup_keys: list[str]) -> set[str]:
        if not dedup_keys:
            return set()
        query = select(cls.dedup_key).where(cls.user_id == user_id, cls.dedup_key.in_(dedup_keys))
        return set((await session.execute(query)).scalars())

    @classmethod
    async def recent(cls, session, user_id: PyUUID, codes: list[str], since: date) -> list[tuple[str, date, int]]:
        """(mã, ngày, payload.severity_rank) đã gửi từ ngày `since`, kể cả đã bỏ qua (cho thời gian chờ)."""
        if not codes:
            return []
        rank = func.coalesce(cls.payload["severity_rank"].as_integer(), 0)
        query = select(cls.code, cls.local_date, rank).where(
            cls.user_id == user_id, cls.code.in_(codes), cls.local_date >= since)
        return [(code, day, int(value)) for code, day, value in (await session.execute(query)).all()]

    @classmethod
    async def titles(cls, session, user_id: PyUUID, kind: str, day: date) -> list[str]:
        query = select(cls.title).where(cls.user_id == user_id, cls.kind == kind, cls.local_date == day)
        return list((await session.execute(query.order_by(cls.created_at))).scalars())

    @classmethod
    async def owned(cls, session, user_id: PyUUID, notification_id: PyUUID) -> UserNotification | None:
        found = await session.get(cls, notification_id)
        return found if found is not None and found.user_id == user_id else None
