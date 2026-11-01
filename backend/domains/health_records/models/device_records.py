"""Wearable health data synchronized from the Google Health API.

Split from models.health in the domain reorganization."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID as PyUUID
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from domains.shared.models.basemodel import BaseModel, utc_now, uuid7
from domains.health_records.schemas.health import HEALTH_PROVIDER


def _user_fk() -> Mapped[PyUUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

def _json(default: str = "'{}'::jsonb"):
    return mapped_column(JSONB(none_as_null=True), default=dict, server_default=text(default), nullable=False)


def _json_list():
    return mapped_column(JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False)


def _source_record():
    """Provenance: the provider record this row was projected from (health_source_records)."""
    return mapped_column(UUID(as_uuid=True), ForeignKey("health_source_records.id", ondelete="SET NULL"),
                         nullable=True)

def _source() -> Mapped[str]:
    return mapped_column(String(20), default=HEALTH_PROVIDER, server_default=HEALTH_PROVIDER, nullable=False)

def _ranges(table: str, ranges: dict[str, tuple[float, float]]) -> list[CheckConstraint]:
    return [CheckConstraint(f"{field} IS NULL OR ({field} >= {low} AND {field} <= {high})", name=f"ck_{table}_{field}")
            for field, (low, high) in ranges.items()]

DAILY_RANGES = {
    "steps": (0, 1_000_000), "distance_m": (0, 1_000_000), "floors": (0, 10_000),
    "active_minutes": (0, 1440), "active_zone_minutes": (0, 2880), "total_kcal": (0, 50_000),
    "active_kcal": (0, 50_000), "resting_hr_bpm": (20, 250), "hr_avg_bpm": (20, 300),
    "hr_min_bpm": (20, 300), "hr_max_bpm": (20, 300), "hrv_ms": (0, 1000), "spo2_avg_pct": (0, 100),
    "respiratory_rate": (0, 100), "vo2_max": (0, 100), "hydration_ml": (0, 100_000),
    "sleep_minutes": (0, 1440), "skin_temp_delta_c": (-20, 20),
}

# Columns a provider rollup may write; the upsert compares exactly these.
DAILY_FIELDS = (*DAILY_RANGES, "active_minutes_by_level", "timezone", "data_source")

SLEEP_FIELDS = ("start_at", "end_at", "local_date", "sleep_type", "is_main", "is_nap", "minutes_asleep",
                "minutes_awake", "minutes_in_period", "minutes_to_fall_asleep", "deep_minutes", "light_minutes",
                "rem_minutes", "awake_minutes", "efficiency_pct", "data_source", "utc_offset_s", "stages",
                "short_awakenings")

WORKOUT_FIELDS = ("started_at", "ended_at", "local_date", "exercise_type", "display_name", "active_seconds",
                  "energy_kcal", "distance_m", "steps", "avg_hr_bpm", "active_zone_minutes", "hr_zone_seconds",
                  "elevation_gain_m", "avg_speed_mps", "run_vo2_max", "data_source", "utc_offset_s",
                  "elapsed_seconds", "pauses", "splits", "has_route")

SAMPLE_FIELDS = ("sample_type", "measured_at", "value", "unit", "details", "data_source", "utc_offset_s")
SAMPLE_TYPES = ("BLOOD_GLUCOSE", "CORE_BODY_TEMPERATURE", "VO2_MAX", "RUN_VO2_MAX", "SLEEP_RESPIRATORY_RATE")

class DailyHealthSummary(BaseModel):
    __tablename__ = "daily_health_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", "source", name="uq_daily_health_user_date_source"),
        CheckConstraint("jsonb_typeof(active_minutes_by_level) = 'object'", name="ck_daily_health_summaries_levels"),
        CheckConstraint("jsonb_typeof(data_source) = 'object'", name="ck_daily_health_summaries_data_source"),
        *_ranges("daily_health_summaries", DAILY_RANGES),
    )

    user_id: Mapped[PyUUID] = _user_fk()
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = _source()
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh", server_default="Asia/Ho_Chi_Minh", nullable=False)
    steps: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    floors: Mapped[int | None] = mapped_column(Integer)
    active_minutes: Mapped[int | None] = mapped_column(Integer)
    active_minutes_by_level: Mapped[dict[str, Any]] = _json()
    active_zone_minutes: Mapped[int | None] = mapped_column(Integer)
    total_kcal: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    active_kcal: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    resting_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    hr_avg_bpm: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    hr_min_bpm: Mapped[int | None] = mapped_column(Integer)
    hr_max_bpm: Mapped[int | None] = mapped_column(Integer)
    hrv_ms: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    spo2_avg_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    respiratory_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    vo2_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    hydration_ml: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    sleep_minutes: Mapped[int | None] = mapped_column(Integer)
    skin_temp_delta_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    data_source: Mapped[dict[str, Any]] = _json()
    source_record_id: Mapped[PyUUID | None] = _source_record()

class SleepSession(BaseModel):
    __tablename__ = "sleep_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_sleep_sessions_external"),
        CheckConstraint("end_at > start_at", name="ck_sleep_sessions_interval"),
        CheckConstraint("jsonb_typeof(data_source) = 'object'", name="ck_sleep_sessions_data_source"),
        *_ranges("sleep_sessions", {field: (0, 2880) for field in (
            "minutes_asleep", "minutes_awake", "minutes_in_period", "minutes_to_fall_asleep",
            "deep_minutes", "light_minutes", "rem_minutes", "awake_minutes")}),
        CheckConstraint("efficiency_pct IS NULL OR (efficiency_pct >= 0 AND efficiency_pct <= 100)",
                        name="ck_sleep_sessions_efficiency_pct"),
        Index("ix_sleep_sessions_user_date", "user_id", "local_date"),
    )

    user_id: Mapped[PyUUID] = _user_fk()
    source: Mapped[str] = _source()
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_type: Mapped[str | None] = mapped_column(String(20))
    is_main: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    is_nap: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    minutes_asleep: Mapped[int | None] = mapped_column(Integer)
    minutes_awake: Mapped[int | None] = mapped_column(Integer)
    minutes_in_period: Mapped[int | None] = mapped_column(Integer)
    minutes_to_fall_asleep: Mapped[int | None] = mapped_column(Integer)
    deep_minutes: Mapped[int | None] = mapped_column(Integer)
    light_minutes: Mapped[int | None] = mapped_column(Integer)
    rem_minutes: Mapped[int | None] = mapped_column(Integer)
    awake_minutes: Mapped[int | None] = mapped_column(Integer)
    efficiency_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    data_source: Mapped[dict[str, Any]] = _json()
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    # Segments as Google recorded them. Short awakenings overlap stages: never add them up.
    stages: Mapped[list[Any]] = _json_list()
    short_awakenings: Mapped[list[Any]] = _json_list()
    source_record_id: Mapped[PyUUID | None] = _source_record()

class DeviceWorkout(BaseModel):
    __tablename__ = "device_workouts"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_device_workouts_external"),
        CheckConstraint("ended_at >= started_at", name="ck_device_workouts_interval"),
        CheckConstraint("jsonb_typeof(hr_zone_seconds) = 'object'", name="ck_device_workouts_zones"),
        CheckConstraint("jsonb_typeof(data_source) = 'object'", name="ck_device_workouts_data_source"),
        *_ranges("device_workouts", {
            "active_seconds": (0, 7 * 86400), "energy_kcal": (0, 50_000), "distance_m": (0, 1_000_000),
            "steps": (0, 1_000_000), "avg_hr_bpm": (20, 300), "active_zone_minutes": (0, 2880),
            "elevation_gain_m": (-100_000, 100_000), "avg_speed_mps": (0, 1000), "run_vo2_max": (0, 100)}),
        Index("ix_device_workouts_user_date", "user_id", "local_date"),
    )

    user_id: Mapped[PyUUID] = _user_fk()
    source: Mapped[str] = _source()
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    exercise_type: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(255))
    active_seconds: Mapped[int | None] = mapped_column(Integer)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    distance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    steps: Mapped[int | None] = mapped_column(Integer)
    avg_hr_bpm: Mapped[int | None] = mapped_column(Integer)
    active_zone_minutes: Mapped[int | None] = mapped_column(Integer)
    hr_zone_seconds: Mapped[dict[str, Any]] = _json()
    elevation_gain_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    avg_speed_mps: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    run_vo2_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    data_source: Mapped[dict[str, Any]] = _json()
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)
    # Device sessions carry pauses and splits, never sets or reps.
    pauses: Mapped[list[Any]] = _json_list()
    splits: Mapped[list[Any]] = _json_list()
    has_route: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    source_record_id: Mapped[PyUUID | None] = _source_record()

class HealthSample(BaseModel):
    """Spot vitals kept only in PostgreSQL; never projected into the knowledge graph."""
    __tablename__ = "health_samples"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "external_id", name="uq_health_samples_external"),
        CheckConstraint("sample_type IN ('BLOOD_GLUCOSE', 'CORE_BODY_TEMPERATURE', 'VO2_MAX', 'RUN_VO2_MAX', "
                        "'SLEEP_RESPIRATORY_RATE')", name="ck_health_samples_type"),
        CheckConstraint("value >= 0 AND value < 10000", name="ck_health_samples_value"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="ck_health_samples_details"),
        CheckConstraint("jsonb_typeof(data_source) = 'object'", name="ck_health_samples_data_source"),
        Index("ix_health_samples_user_measured", "user_id", "measured_at"),
    )

    user_id: Mapped[PyUUID] = _user_fk()
    source: Mapped[str] = _source()
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sample_type: Mapped[str] = mapped_column(String(30), nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict[str, Any]] = _json()
    data_source: Mapped[dict[str, Any]] = _json()
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    source_record_id: Mapped[PyUUID | None] = _source_record()

async def upsert_rows(session: AsyncSession, model, rows: list[dict[str, Any]], *, keys: tuple[str, ...],
                      fields: tuple[str, ...]) -> int:
    """Insert or update provider rows; returns how many rows were written.

    Unchanged rows are skipped by the WHERE clause, so their version and the graph
    projection stay put. A previously soft-deleted record is revived when it returns.
    """
    if not rows:
        return 0
    table = model.__table__
    now = utc_now()
    values = [{"id": uuid7(), "created_at": now, "updated_at": now, "version_id": 1, "is_active": True, **row}
              for row in rows]
    statement = insert(table).values(values)
    excluded = statement.excluded
    changed = [table.c[field].is_distinct_from(excluded[field]) for field in fields]
    changed.append(table.c.is_active.is_(False))
    # Provider rows always carry external_id. The predicate lets PostgreSQL infer the partial
    # unique indexes of the log tables (WHERE external_id IS NOT NULL) as well as full ones.
    index_where = table.c.external_id.isnot(None) if "external_id" in keys else None
    statement = statement.on_conflict_do_update(
        index_elements=[table.c[key] for key in keys],
        index_where=index_where,
        set_={**{field: excluded[field] for field in fields}, "is_active": True,
              "updated_at": func.now(), "version_id": table.c.version_id + 1},
        where=or_(*changed),
    ).returning(table.c.id)
    result = await session.execute(statement)
    return len(result.fetchall())
