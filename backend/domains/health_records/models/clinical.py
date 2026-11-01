"""Bản ghi cấp lâm sàng của nhà cung cấp và metadata thiết bị (migration 0020).

ECG và IRN giữ phân loại của nhà cung cấp cùng metadata thiết bị/thuật toán;
HercFit không bao giờ diễn giải lại chúng. Dạng sóng ECG được giữ nén trong
PostgreSQL có thời hạn lưu: nó không bao giờ đến knowledge graph hay prompt.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from domains.health_records.models.device_records import _json_list, _source, _source_record, _user_fk
from domains.shared.models.basemodel import BaseModel


class EcgRecording(BaseModel):
    __tablename__ = "ecg_recordings"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_ecg_recordings_external"),
        CheckConstraint("ended_at >= started_at", name="ck_ecg_recordings_interval"),
        Index("ix_ecg_recordings_user_date", "user_id", "local_date"),
    )

    user_id: Mapped[PyUUID] = _user_fk()
    source: Mapped[str] = _source()
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    classification: Mapped[str | None] = mapped_column(String(40))
    avg_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    sampling_hz: Mapped[int | None] = mapped_column(Integer)
    lead_number: Mapped[int | None] = mapped_column(Integer)
    device_model: Mapped[str | None] = mapped_column(String(120))
    algorithm_version: Mapped[str | None] = mapped_column(String(60))
    waveform_zlib: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    waveform_samples: Mapped[int | None] = mapped_column(Integer)
    retention_until: Mapped[date | None] = mapped_column(Date)
    source_record_id: Mapped[PyUUID | None] = _source_record()


class IrnAlert(BaseModel):
    __tablename__ = "irn_alerts"
    __table_args__ = (UniqueConstraint("user_id", "source", "external_id", name="uq_irn_alerts_external"),)

    user_id: Mapped[PyUUID] = _user_fk()
    source: Mapped[str] = _source()
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    positive_windows: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    windows: Mapped[list[Any]] = _json_list()
    device_model: Mapped[str | None] = mapped_column(String(120))
    algorithm_version: Mapped[str | None] = mapped_column(String(60))
    source_record_id: Mapped[PyUUID | None] = _source_record()


class WorkoutRoute(Base):
    __tablename__ = "workout_routes"

    workout_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("device_workouts.id", ondelete="CASCADE"),
                                               primary_key=True)
    user_id: Mapped[PyUUID] = _user_fk()
    format: Mapped[str] = mapped_column(String(10), default="TCX", server_default="TCX", nullable=False)
    data_zlib: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    partial: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    retention_until: Mapped[date | None] = mapped_column(Date)


class PairedDevice(BaseModel):
    __tablename__ = "paired_devices"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_paired_devices_external"),)

    user_id: Mapped[PyUUID] = _user_fk()
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("health_connections.id",
                                                                                 ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    device_type: Mapped[str | None] = mapped_column(String(20))
    device_version: Mapped[str | None] = mapped_column(String(120))
    battery_level: Mapped[int | None] = mapped_column(Integer)
    battery_status: Mapped[str | None] = mapped_column(String(40))
    features: Mapped[list[Any]] = _json_list()
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
