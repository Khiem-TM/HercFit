"""The source layer: provider records as received, and compressed dense series (migration 0019).

Provider-agnostic: a row names its connection, data type and the provider's
resource name. Business rows point back here (`source_record_id`), so every
number HercFit shows or gives the assistant can be traced to what was received.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from domains.shared.models.basemodel import uuid7


def _uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


def _json(default: str = "'{}'::jsonb", factory=dict):
    return mapped_column(JSONB(none_as_null=True), default=factory, server_default=text(default), nullable=False)


class HealthSourceRecord(Base):
    __tablename__ = "health_source_records"
    __table_args__ = (
        UniqueConstraint("connection_id", "data_type", "resource_name", name="uq_health_source_records_resource"),
        CheckConstraint("record_kind IN ('POINT', 'DAILY_ROLLUP', 'PROFILE')", name="ck_health_source_records_kind"),
        CheckConstraint("deletion_state IN ('PRESENT', 'DELETED_REMOTE', 'SUPERSEDED')",
                        name="ck_health_source_records_deletion"),
        Index("ix_health_source_records_window", "connection_id", "data_type", "civil_date"),
        Index("ix_health_source_records_user", "user_id", "data_type", "physical_start"),
        Index("ix_health_source_records_retention", "retention_until",
              postgresql_where=text("retention_until IS NOT NULL")),
    )

    id: Mapped[PyUUID] = _uuid_pk()
    connection_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("health_connections.id",
                                                                                 ondelete="CASCADE"), nullable=False)
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    data_type: Mapped[str] = mapped_column(String(60), nullable=False)
    record_kind: Mapped[str] = mapped_column(String(20), default="POINT", server_default="POINT", nullable=False)
    resource_name: Mapped[str] = mapped_column(String(300), nullable=False)
    api_version: Mapped[str] = mapped_column(String(8), nullable=False)
    schema_revision: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    data_source: Mapped[dict[str, Any]] = _json()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    quality: Mapped[dict[str, Any]] = _json()
    unknown_paths: Mapped[list[Any]] = _json("'[]'::jsonb", list)
    physical_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    physical_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    civil_start: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False))
    civil_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=False))
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    civil_date: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_root: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True))
    deletion_state: Mapped[str] = mapped_column(String(20), default="PRESENT", server_default="PRESENT", nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, default=1, server_default=text("1"), nullable=False)
    retention_until: Mapped[date | None] = mapped_column(Date)


class HealthSeriesChunk(Base):
    __tablename__ = "health_series_chunks"
    __table_args__ = (
        UniqueConstraint("user_id", "data_type", "source_key", "chunk_start", name="uq_health_series_chunks"),
        CheckConstraint("chunk_end > chunk_start", name="ck_health_series_chunks_span"),
        CheckConstraint("resolution IN ('hour', 'day')", name="ck_health_series_chunks_resolution"),
        CheckConstraint("sample_count >= 0", name="ck_health_series_chunks_count"),
        Index("ix_health_series_chunks_range", "user_id", "data_type", "chunk_start"),
    )

    id: Mapped[PyUUID] = _uuid_pk()
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    connection_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("health_connections.id",
                                                                                        ondelete="CASCADE"))
    data_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chunk_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution: Mapped[str] = mapped_column(String(10), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    encoding: Mapped[str] = mapped_column(String(12), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    value_min: Mapped[float | None] = mapped_column(Float)
    value_max: Mapped[float | None] = mapped_column(Float)
    value_sum: Mapped[float | None] = mapped_column(Float)
    covered_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_revision: Mapped[str] = mapped_column(String(20), nullable=False)
    retention_until: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HealthRecordLink(Base):
    __tablename__ = "health_record_links"
    __table_args__ = (
        CheckConstraint("link_kind IN ('PROJECTED', 'MERGED', 'EXPORTED')", name="ck_health_record_links_kind"),
        Index("ix_health_record_links_business", "business_table", "business_id"),
    )

    source_record_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("health_source_records.id",
                                                                                    ondelete="CASCADE"),
                                                     primary_key=True)
    business_table: Mapped[str] = mapped_column(String(60), primary_key=True)
    business_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    link_kind: Mapped[str] = mapped_column(String(20), default="PROJECTED", server_default="PROJECTED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
