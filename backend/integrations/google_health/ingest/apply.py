"""From the source layer to business tables (primary mode) or to a comparison (shadow mode).

`build(...)` re-parses the PRESENT source records of one data type and civil
window with the adapter of the API version that produced them, and projects them
exactly as the in-process sync does. `apply(...)` writes them (reusing
sync.store for the families it already covers, so the deletion rules are the same
tested ones) and links each business row to its source record. `compare(...)`
reports what primary mode would change, without writing business tables.
"""
from __future__ import annotations

import zlib
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from domains.health_records.models.clinical import EcgRecording, IrnAlert
from domains.health_records.models.device_records import (
    SAMPLE_FIELDS, DailyHealthSummary, DeviceWorkout, HealthSample, SleepSession, upsert_rows,
)
from domains.health_records.schemas.health import HEALTH_PROVIDER
from domains.nutrition.models.logs import HydrationLog, NutritionLog
from integrations.google_health import projections
from integrations.google_health.adapters import adapter
from integrations.google_health.ingest import stage
from integrations.google_health.sync import (
    BODY_TYPES, COMPLETE, DAILY_TYPES, ROLLUP_TYPES, SAMPLE_TYPES, TYPE_COLUMNS, TypeRead, Window, store,
)

ROLLUP, POINTS = "rollup", "points"
ECG_FIELDS = ("started_at", "ended_at", "utc_offset_s", "local_date", "classification", "avg_hr_bpm", "sampling_hz",
              "lead_number", "device_model", "algorithm_version", "waveform_samples")
IRN_FIELDS = ("started_at", "ended_at", "utc_offset_s", "local_date", "positive_windows", "windows", "device_model",
              "algorithm_version")
HYDRATION_FIELDS = ("consumed_at", "utc_offset_s", "local_date", "amount_ml", "user_unit")
NUTRITION_FIELDS = ("consumed_at", "ended_at", "utc_offset_s", "local_date", "meal_type", "food_name", "energy_kcal",
                    "protein_g", "carbohydrate_g", "fat_g", "nutrients", "serving")
LINK_TABLES = {"sleep": "sleep_sessions", "exercise": "device_workouts", "weight": "body_metrics",
               "height": "body_metrics", "body-fat": "body_metrics", "electrocardiogram": "ecg_recordings",
               "irregular-rhythm-notification": "irn_alerts", "hydration-log": "hydration_logs",
               "nutrition-log": "nutrition_logs",
               **{t: "health_samples" for t in (*SAMPLE_TYPES, *projections.EXTRA_SAMPLES)}}


def family(data_type: str, mode: str) -> str:
    if mode == ROLLUP:
        return "daily_rollup"
    if data_type in DAILY_TYPES:
        return "daily"
    if data_type in BODY_TYPES:
        return "body"
    if data_type in SAMPLE_TYPES or data_type in projections.EXTRA_SAMPLES:
        return "sample"
    return {"sleep": "session", "exercise": "session", "electrocardiogram": "ecg",
            "irregular-rhythm-notification": "irn", "hydration-log": "hydration_log",
            "nutrition-log": "nutrition_log"}.get(data_type, "source_only")


async def build(session, *, connection_id: UUID, data_type: str, mode: str, start: date, end: date,
                zone: str) -> dict[str, Any]:
    """Business rows for one type and window, from PRESENT source records only."""
    from integrations.google_health.export import selfsource

    owned = await selfsource.owned_names(session, connection_id, data_type)
    records = [record for record in await stage.present(session, connection_id=connection_id, data_type=data_type,
                                                        start=start, end=end)
               # Points HercFit exported are already local records: never import them back.
               if record.resource_name not in owned and not selfsource.written_by_us(record.data_source)]
    read = TypeRead(data_type, COMPLETE, points=len(records))
    fetched: dict[str, Any] = {"days": {}, "types": {data_type: read}, "body": [], "samples": [], "sleep": [],
                               "workouts": [], "ecg": [], "irn": [], "hydration": [], "nutrition": [],
                               "records": {}}
    window = Window(start, end, zone)
    for record in records:
        if (mode == ROLLUP) != (record.record_kind == "DAILY_ROLLUP"):
            continue
        parser = adapter(record.api_version)
        parsed = (parser.parse_rollup(data_type, record.payload, daily=True) if mode == ROLLUP
                  else parser.parse_point(data_type, record.payload))
        if any(code == "BAD_TYPE" for code in parsed.quality.values()):
            read.rejected += 1
        key = projections.external_id(parsed, parsed.time.physical_start)
        read.seen.add(key)
        fetched["records"][key] = record.id
        kind = family(data_type, mode)
        if kind == "daily_rollup":
            if window.contains(parsed.time.civil_date):
                projections.merge_days(fetched["days"], parsed.time.civil_date, projections.rollup_columns(parsed))
        elif kind == "daily":
            if window.contains(parsed.time.civil_date):
                projections.merge_days(fetched["days"], parsed.time.civil_date, projections.daily_columns(parsed))
        elif kind == "body":
            row = projections.body_row(parsed)
            if row is not None:
                fetched["body"].append(row)
        elif kind == "sample":
            row = projections.sample_row(parsed)
            if row is not None:
                fetched["samples"].append(row)
        elif kind == "session":
            row = (projections.sleep_row if data_type == "sleep" else projections.workout_row)(parsed, zone)
            if row is not None and window.contains(row["local_date"]):
                fetched["sleep" if data_type == "sleep" else "workouts"].append(row)
        elif kind == "ecg":
            row = projections.ecg_row(parsed, zone)
            if row is not None:
                waveform = projections.ecg_waveform(parsed)
                row["waveform_zlib"] = zlib.compress(",".join(map(str, waveform)).encode()) if waveform else None
                fetched["ecg"].append(row)
        elif kind == "irn":
            row = projections.irn_row(parsed, zone)
            if row is not None:
                fetched["irn"].append(row)
        elif kind == "hydration_log":
            row = projections.hydration_row(parsed, zone)
            if row is not None:
                fetched["hydration"].append(row)
        elif kind == "nutrition_log":
            row = projections.nutrition_row(parsed, zone)
            if row is not None:
                fetched["nutrition"].append(row)
    if data_type == "sleep":
        for day, minutes in projections.main_sleep_minutes(fetched["sleep"]).items():
            projections.merge_days(fetched["days"], day, {"sleep_minutes": minutes})
    return fetched


async def _upsert_and_sweep(session, model, rows: list[dict], fields: tuple[str, ...], *, user_id: UUID,
                            keep: set[str], column: str, low, high, clean: bool, where: str = "",
                            params: dict | None = None) -> dict[str, int]:
    payload = [{"user_id": user_id, "source": HEALTH_PROVIDER, **row} for row in rows]
    written = await upsert_rows(session, model, payload, keys=("user_id", "source", "external_id"), fields=fields)
    removed = 0
    if clean:
        result = await session.execute(text(f"""
            UPDATE {model.__tablename__} SET is_active = false, updated_at = now(), version_id = version_id + 1
            WHERE user_id = :uid AND source = :source AND is_active AND {column} >= :low AND {column} <= :high
              AND NOT (external_id = ANY(CAST(:keep AS text[]))) {where}"""),
            {"uid": user_id, "source": HEALTH_PROVIDER, "low": low, "high": high, "keep": sorted(keep),
             **(params or {})})
        removed = result.rowcount or 0
    return {"written": written, "removed": removed}


async def _link(session, *, connection_id: UUID, user_id: UUID, data_type: str) -> None:
    table = LINK_TABLES.get(data_type)
    if table is None:
        return
    await session.execute(text(f"""
        UPDATE {table} b SET source_record_id = s.id
        FROM health_source_records s
        WHERE s.connection_id = :connection AND s.data_type = :data_type AND s.deletion_state = 'PRESENT'
          AND b.user_id = :uid AND b.source = :source AND b.external_id = s.resource_name
          AND b.source_record_id IS DISTINCT FROM s.id"""),
        {"connection": connection_id, "data_type": data_type, "uid": user_id, "source": HEALTH_PROVIDER})


async def apply(session, *, connection_id: UUID, user_id: UUID, data_type: str, mode: str, start: date, end: date,
                zone: str) -> dict[str, Any]:
    """Write business rows for a completed window. The caller has fenced the job in this transaction."""
    from integrations.google_health.export.capture import mark_import

    await mark_import(session)
    fetched = await build(session, connection_id=connection_id, data_type=data_type, mode=mode, start=start, end=end,
                          zone=zone)
    kind = family(data_type, mode)
    read: TypeRead = fetched["types"][data_type]
    window = Window(start, end, zone)
    clean = read.rejected == 0
    if kind in ("daily_rollup", "daily", "body", "session") or (kind == "sample" and data_type in SAMPLE_TYPES):
        outcome = await store(session, user_id, window, fetched)
        if kind == "body" and clean:
            # Per-type removal: only rows of this body type (resource names carry the type).
            removed = await session.execute(text("""
                UPDATE body_metrics SET is_active = false, updated_at = now(), version_id = version_id + 1
                WHERE user_id = :uid AND source = :source AND is_active AND recorded_at >= :low AND recorded_at < :high
                  AND (external_id LIKE :resource OR external_id LIKE :local)
                  AND NOT (external_id = ANY(CAST(:keep AS text[])))"""),
                {"uid": user_id, "source": HEALTH_PROVIDER, "low": window.utc_start, "high": window.utc_end,
                 "resource": f"%/dataTypes/{data_type}/%", "local": f"{data_type}:%", "keep": sorted(read.seen)})
            outcome["counts"]["body_metrics_removed"] = removed.rowcount or 0
    elif kind == "sample":
        sample_type = projections.EXTRA_SAMPLES[data_type][0]
        outcome = {"counts": {"health_samples": await _upsert_and_sweep(
            session, HealthSample, fetched["samples"], SAMPLE_FIELDS, user_id=user_id, keep=read.seen,
            column="measured_at", low=window.utc_start, high=window.utc_end, clean=clean,
            where="AND sample_type = :sample_type", params={"sample_type": sample_type})}, "errors": {}}
    elif kind == "ecg":
        rows = fetched["ecg"]
        outcome = {"counts": {"ecg_recordings": await _upsert_and_sweep(
            session, EcgRecording, rows, (*ECG_FIELDS, "waveform_zlib"), user_id=user_id, keep=read.seen,
            column="local_date", low=start, high=end, clean=clean)}, "errors": {}}
    elif kind == "irn":
        outcome = {"counts": {"irn_alerts": await _upsert_and_sweep(
            session, IrnAlert, fetched["irn"], IRN_FIELDS, user_id=user_id, keep=read.seen, column="local_date",
            low=start, high=end, clean=clean)}, "errors": {}}
    elif kind == "hydration_log":
        outcome = {"counts": {"hydration_logs": await _upsert_and_sweep(
            session, HydrationLog, fetched["hydration"], HYDRATION_FIELDS, user_id=user_id, keep=read.seen,
            column="local_date", low=start, high=end, clean=clean)}, "errors": {}}
    elif kind == "nutrition_log":
        outcome = {"counts": {"nutrition_logs": await _upsert_and_sweep(
            session, NutritionLog, fetched["nutrition"], NUTRITION_FIELDS, user_id=user_id, keep=read.seen,
            column="local_date", low=start, high=end, clean=clean)}, "errors": {}}
    else:
        outcome = {"counts": {}, "errors": {}}
    await _link(session, connection_id=connection_id, user_id=user_id, data_type=data_type)
    return outcome


# ------------------------------------------------------------------------------------------- shadow
def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float, Decimal)) and isinstance(right, (int, float, Decimal)):
        return abs(float(left) - float(right)) <= 0.051
    return left == right


async def compare(session, *, connection_id: UUID, user_id: UUID, data_type: str, mode: str, start: date, end: date,
                  zone: str) -> list[dict[str, Any]]:
    """Differences between what the source layer implies and what the business tables hold."""
    fetched = await build(session, connection_id=connection_id, data_type=data_type, mode=mode, start=start, end=end,
                          zone=zone)
    kind = family(data_type, mode)
    diffs: list[dict[str, Any]] = []
    if kind in ("daily_rollup", "daily") or data_type == "sleep":
        columns = TYPE_COLUMNS.get(data_type, ())
        stored = {row.local_date: row for row in (await session.execute(select(DailyHealthSummary).where(
            DailyHealthSummary.user_id == user_id, DailyHealthSummary.source == HEALTH_PROVIDER,
            DailyHealthSummary.is_active.is_(True), DailyHealthSummary.local_date >= start,
            DailyHealthSummary.local_date <= end))).scalars()}
        for day in sorted(set(fetched["days"]) | set(stored)):
            expected = fetched["days"].get(day, {})
            row = stored.get(day)
            for column in columns:
                if column == "active_minutes_by_level":
                    continue
                have = getattr(row, column) if row is not None else None
                want = expected.get(column)
                if not _same(have, want) and not (have is None and want is None):
                    diffs.append({"kind": "value", "day": day.isoformat(), "column": column,
                                  "stored": None if have is None else float(have) if isinstance(have, Decimal) else have,
                                  "source": want})
    if kind == "session":
        model = SleepSession if data_type == "sleep" else DeviceWorkout
        rows = fetched["sleep" if data_type == "sleep" else "workouts"]
        stored = set((await session.execute(select(model.external_id).where(
            model.user_id == user_id, model.source == HEALTH_PROVIDER, model.is_active.is_(True),
            model.local_date >= start, model.local_date <= end))).scalars())
        expected = {row["external_id"] for row in rows}
        for name in sorted(expected - stored):
            diffs.append({"kind": "missing_in_business", "external_id": name})
        for name in sorted(stored - expected):
            diffs.append({"kind": "extra_in_business", "external_id": name})
    return diffs
