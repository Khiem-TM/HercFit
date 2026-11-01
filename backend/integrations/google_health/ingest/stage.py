"""Staging provider points into health_source_records, and mark-and-sweep deletion.

* Identity: Google's resource name when the type is identifiable; otherwise a
  stable key from the type, the observation time and the data source, so a
  re-read updates the same row instead of creating a new one.
* Every staged row records the root fetch that saw it (`last_seen_root`). When a
  fetch of a window completes cleanly, rows of that window it did not see are
  marked DELETED_REMOTE. Missing pages, parse errors or a lost permission never
  get that far, so they never delete anything.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert

from domains.health_records.models.sources import HealthSourceRecord
from domains.shared.models.basemodel import uuid7
from integrations.google_health.adapters.base import Parsed
from integrations.google_health.contract.registry import DISCOVERY_REVISION, Retention, spec

ALL_SOURCES = "all-sources"
RETENTION_DAYS = {Retention.DETAIL_90D: 90, Retention.AGGREGATE_2Y: 730, Retention.RECORD_2Y: 730,
                  Retention.SESSION_META_2Y: 730}


def source_key(parsed: Parsed) -> str:
    """Opaque, stable id of the recording source (device/app/platform); never merged across sources."""
    source = parsed.data_source or {}
    device = source.get("device") or {}
    application = source.get("application") or {}
    parts = [source.get("platform"), source.get("recordingMethod"), device.get("manufacturer"),
             device.get("displayName"), device.get("formFactor"), application.get("packageName"),
             application.get("googleWebClientId"), application.get("webClientId")]
    if not any(parts):
        return ALL_SOURCES
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode()).hexdigest()[:16]


def resource_name(parsed: Parsed, *, rollup: bool = False) -> str:
    if rollup:
        return f"rollup:{parsed.data_type}:{parsed.time.civil_date.isoformat() if parsed.time.civil_date else 'unknown'}"
    if parsed.resource_name:
        return parsed.resource_name[:300]
    moment = parsed.time.physical_start.isoformat() if parsed.time.physical_start else "undated"
    end = parsed.time.physical_end.isoformat() if parsed.time.physical_end else ""
    return f"{parsed.data_type}:{moment}:{end}:{source_key(parsed)}"[:300]


def retention_until(data_type: str, day: date | None) -> date | None:
    if day is None:
        return None
    return day + timedelta(days=RETENTION_DAYS[spec(data_type).retention])


def _canonical(raw: dict[str, Any]) -> str:
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def civil_date(parsed: Parsed, zone: str | None) -> date | None:
    """The point's own civil date; for points that carry no offset nor civil time (old devices),
    the connection's timezone decides, so they still belong to a window."""
    if parsed.time.civil_date is not None:
        return parsed.time.civil_date
    moment = parsed.time.physical_end if parsed.data_type == "sleep" else parsed.time.physical_start
    if moment is None or zone is None:
        return None
    from zoneinfo import ZoneInfo
    return moment.astimezone(ZoneInfo(zone)).date()


async def stage(session, *, connection_id: UUID, user_id: UUID, generation: int, root_id: UUID,
                points: list[tuple[Parsed, dict[str, Any]]], rollup: bool = False, zone: str | None = None) -> int:
    """Upsert staged points; returns how many rows were inserted or changed."""
    if not points:
        return 0
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for parsed, raw in points:
        if parsed.time.civil_date is None:
            parsed.time.civil_date = civil_date(parsed, zone)
        payload = _canonical(raw)
        name = resource_name(parsed, rollup=rollup)
        rows[(parsed.data_type, name)] = {
            "id": uuid7(), "connection_id": connection_id, "user_id": user_id, "data_type": parsed.data_type,
            "record_kind": "DAILY_ROLLUP" if rollup else "POINT", "resource_name": name,
            "api_version": parsed.api_version, "schema_revision": DISCOVERY_REVISION,
            "source_key": ALL_SOURCES if rollup else source_key(parsed), "data_source": raw.get("dataSource") or {},
            "payload": raw, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "quality": parsed.quality, "unknown_paths": parsed.unknown_paths,
            "physical_start": parsed.time.physical_start, "physical_end": parsed.time.physical_end,
            "civil_start": parsed.time.civil_start, "civil_end": parsed.time.civil_end,
            "utc_offset_s": parsed.time.start_offset_s, "civil_date": parsed.time.civil_date,
            "last_seen_root": root_id, "deletion_state": "PRESENT", "generation": generation,
            "retention_until": retention_until(parsed.data_type, parsed.time.civil_date),
        }
    table = HealthSourceRecord.__table__
    statement = insert(table).values(list(rows.values()))
    excluded = statement.excluded
    changed = ["payload_sha256", "quality", "unknown_paths", "deletion_state", "civil_date", "api_version"]
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.connection_id, table.c.data_type, table.c.resource_name],
        set_={**{name: excluded[name] for name in (
            "payload", "payload_sha256", "quality", "unknown_paths", "data_source", "physical_start", "physical_end",
            "civil_start", "civil_end", "utc_offset_s", "civil_date", "api_version", "schema_revision",
            "generation", "retention_until", "source_key")},
              "last_seen_root": excluded.last_seen_root, "deletion_state": "PRESENT", "fetched_at": func.now()},
    ).returning(table.c.id, *[table.c[name] for name in changed[:1]])
    result = await session.execute(statement)
    return len(result.fetchall())


async def sweep(session, *, connection_id: UUID, data_type: str, root_id: UUID, start: date, end: date) -> list[str]:
    """After a complete, clean fetch of [start, end]: rows it did not see were deleted at the provider."""
    result = await session.execute(text("""
        UPDATE health_source_records SET deletion_state = 'DELETED_REMOTE', fetched_at = now()
        WHERE connection_id = :connection AND data_type = :data_type AND deletion_state = 'PRESENT'
          AND civil_date >= :start AND civil_date <= :end
          AND last_seen_root IS DISTINCT FROM :root
        RETURNING resource_name"""), {"connection": connection_id, "data_type": data_type, "root": root_id,
                                      "start": start, "end": end})
    return [row[0] for row in result]


async def present(session, *, connection_id: UUID, data_type: str, start: date, end: date) -> list[HealthSourceRecord]:
    from sqlalchemy import select

    return list((await session.execute(select(HealthSourceRecord).where(
        HealthSourceRecord.connection_id == connection_id, HealthSourceRecord.data_type == data_type,
        HealthSourceRecord.deletion_state == "PRESENT", HealthSourceRecord.civil_date >= start,
        HealthSourceRecord.civil_date <= end).order_by(HealthSourceRecord.physical_start))).scalars())
