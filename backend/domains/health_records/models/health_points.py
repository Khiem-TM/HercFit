"""Bảng `health_points`: mọi dữ liệu đọc từ Google Health, một dòng một data point.

Dạng bản ghi (`kind`) là một trong 5 interface (interval, sample, daily, session, food) và `value`
giữ nguyên đối tượng giá trị Google trả về. Bảng là bản sao của Google: mỗi lần đồng bộ thay thế
nguyên cửa sổ đã đọc trọn vẹn, nên không có phiên bản hay xoá mềm. Ánh xạ sang chỉ số HercFit nằm
ở domains/health_records/views.py.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    delete,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from domains.shared.models.basemodel import uuid7


class HealthPoint(Base):
    __tablename__ = "health_points"
    __table_args__ = (
        UniqueConstraint("user_id", "data_type", "remote_name", name="uq_health_points_remote"),
        Index("ix_health_points_user_type_day", "user_id", "data_type", "local_date"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    data_type: Mapped[str] = mapped_column(String(48), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    remote_name: Mapped[str] = mapped_column(String(300), nullable=False)
    written_by_hercfit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    @classmethod
    async def upsert(cls, session, rows: Iterable[dict[str, Any]]) -> list[PyUUID]:
        """Thêm hoặc cập nhật theo (user, loại, tên Google); id giữ ổn định qua các lần đọc lại."""
        unique = list({(row["data_type"], row["remote_name"]): row for row in rows}.values())
        ids: list[PyUUID] = []
        for offset in range(0, len(unique), 1000):  # giới hạn 65535 tham số mỗi câu lệnh
            statement = insert(cls).values(unique[offset:offset + 1000])
            statement = statement.on_conflict_do_update(
                constraint="uq_health_points_remote",
                set_={column: statement.excluded[column] for column in
                      ("kind", "start_at", "end_at", "local_date", "value", "written_by_hercfit")}
                     | {"updated_at": func.now()},
            ).returning(cls.id)
            ids.extend((await session.execute(statement)).scalars())
        return ids

    @classmethod
    async def replace_window(cls, session, user_id: PyUUID, data_type: str, start: date, end: date,
                             rows: list[dict[str, Any]]) -> tuple[int, int]:
        """Cửa sổ [start, end) của một loại khớp đúng những gì Google vừa trả về (đã đọc trọn vẹn).

        Trả về (số dòng ghi, số dòng bị xoá vì Google không còn giữ)."""
        kept = await cls.upsert(session, rows)
        removed = await session.execute(delete(cls).where(
            cls.user_id == user_id, cls.data_type == data_type, cls.local_date >= start, cls.local_date < end,
            cls.id.not_in(kept) if kept else text("true")))
        return len(kept), removed.rowcount or 0

    @classmethod
    async def remove(cls, session, user_id: PyUUID, data_type: str, remote_name: str) -> int:
        result = await session.execute(delete(cls).where(
            cls.user_id == user_id, cls.data_type == data_type, cls.remote_name == remote_name))
        return result.rowcount or 0
