"""Leased, idempotent synchronization of one Google Health connection.

1. Claim a lease (SKIP LOCKED) and commit: no transaction is held during HTTP.
2. Refresh the access token when it is about to expire; invalid_grant marks the
   connection NEEDS_REAUTH (Testing-mode refresh tokens expire after 7 days).
3. Read every data type the user granted, within the window: a backfill on the
   first run, then from the last synced day minus an overlap for late uploads.
4. Write each data type in its own savepoint. Records the provider no longer
   returns inside a fully read window are deactivated. One failing type makes
   the run PARTIAL instead of losing the others.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from core.crypto import TokenCipherUnavailable, decrypt_secret, encrypt_secret
from core.database import get_db_session
from core.settings import settings
from models.body_metrics import BodyMetric
from models.health import (
    DAILY_FIELDS, SAMPLE_FIELDS, SLEEP_FIELDS, WORKOUT_FIELDS, DailyHealthSummary, DeviceWorkout,
    HealthConnection, HealthSample, HealthSyncRun, SleepSession, upsert_rows,
)
from schemas.health import HEALTH_PROVIDER
from schemas.tracking import DEFAULT_TIMEZONE, day_bounds
from services.google_health import mappers, oauth
from services.google_health.client import GoogleHealthClient, GoogleHealthError, ReauthRequired, field_path

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=10)
OVERLAP_DAYS = 3
TOKEN_SKEW = timedelta(seconds=60)

# data type: (scope key, maximum rollup range in days)
ROLLUP_TYPES = {
    "steps": ("activity", 90), "distance": ("activity", 90), "floors": ("activity", 90),
    "active-minutes": ("activity", 14), "active-zone-minutes": ("activity", 90),
    "total-calories": ("activity", 14), "active-energy-burned": ("activity", 90),
    "heart-rate": ("health_metrics", 14), "hydration-log": ("nutrition", 90),
}
DAILY_TYPES = {
    "daily-resting-heart-rate": "health_metrics", "daily-heart-rate-variability": "health_metrics",
    "daily-oxygen-saturation": "health_metrics", "daily-respiratory-rate": "health_metrics",
    "daily-sleep-temperature-derivations": "health_metrics", "daily-vo2-max": "activity",
}
BODY_TYPES = {"weight": "health_metrics", "height": "health_metrics", "body-fat": "health_metrics"}
SAMPLE_TYPES = {"blood-glucose": "health_metrics", "core-body-temperature": "health_metrics"}
SESSION_TYPES = {"sleep": "sleep", "exercise": "activity"}
# Which daily columns each type fills; a column is only written when its type was read.
TYPE_COLUMNS: dict[str, tuple[str, ...]] = {
    **{data_type: tuple(column for column, *_ in mappers.ROLLUPS[data_type]) for data_type in mappers.ROLLUPS},
    "active-minutes": ("active_minutes", "active_minutes_by_level"),
    **{data_type: tuple(column for column, *_ in mappers.DAILY_POINTS[data_type]) for data_type in mappers.DAILY_POINTS},
    "daily-sleep-temperature-derivations": ("skin_temp_delta_c",),
    "sleep": ("sleep_minutes",),
}


def _chunks(start: date, end_exclusive: date, days: int):
    while start < end_exclusive:
        stop = min(end_exclusive, start + timedelta(days=days))
        yield start, stop
        start = stop


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Window:
    def __init__(self, start: date, end: date, zone: str):
        self.start, self.end, self.zone = start, end, zone
        self.utc_start, self.utc_end = day_bounds(start, end, zone)

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def sync_window(connection: HealthConnection, today: date) -> Window:
    zone = connection.timezone or DEFAULT_TIMEZONE
    earliest = today - timedelta(days=settings.GOOGLE_HEALTH_BACKFILL_DAYS - 1)
    cursor = mappers.as_date((connection.sync_cursor or {}).get("last_window_end"))
    if connection.last_success_at is None or cursor is None:
        return Window(earliest, today, zone)
    return Window(max(earliest, min(cursor, today) - timedelta(days=OVERLAP_DAYS)), today, zone)


async def _claim(session, connection_id: UUID | None, token: UUID) -> UUID | None:
    """Lease one connection: a specific one (manual sync) or the most overdue one."""
    selector = "id = :id" if connection_id else "next_sync_at <= now()"
    row = (await session.execute(text(f"""
        UPDATE health_connections SET lease_token = :token, lease_until = now() + make_interval(secs => :lease)
        WHERE id = (SELECT id FROM health_connections
                    WHERE {selector} AND status = 'ACTIVE' AND is_active
                      AND (lease_until IS NULL OR lease_until < now())
                    ORDER BY next_sync_at NULLS FIRST LIMIT 1 FOR UPDATE SKIP LOCKED)
        RETURNING id"""), {"id": connection_id, "token": token, "lease": LEASE.total_seconds()})).first()
    return row[0] if row else None


async def _release(connection_id: UUID, token: UUID) -> None:
    async with get_db_session() as session:
        await session.execute(text("UPDATE health_connections SET lease_token = NULL, lease_until = NULL "
                                   "WHERE id = :id AND lease_token = :token"), {"id": connection_id, "token": token})


async def sync_connection(connection_id: UUID | None = None, *, trigger: str | None = None,
                          http: httpx.AsyncClient | None = None, today: date | None = None) -> dict[str, Any]:
    """Synchronize one connection (or the most overdue one); returns the run summary."""
    token = uuid4()
    async with get_db_session() as session:
        claimed = await _claim(session, connection_id, token)
    if claimed is None:
        return {"status": "busy" if connection_id else "idle"}
    try:
        if http is not None:
            return await _run(claimed, trigger, http, today)
        async with httpx.AsyncClient() as client:
            return await _run(claimed, trigger, client, today)
    finally:
        await _release(claimed, token)


async def _start(connection_id: UUID, trigger: str | None, today: date | None):
    async with get_db_session() as session:
        connection = await session.get(HealthConnection, connection_id)
        zone = connection.timezone or DEFAULT_TIMEZONE
        today = today or datetime.now(ZoneInfo(zone)).date()
        window = sync_window(connection, today)
        run = HealthSyncRun(connection_id=connection.id, user_id=connection.user_id,
                            trigger=trigger or ("INITIAL" if connection.last_success_at is None else "SCHEDULED"),
                            status="RUNNING", window_start=window.start, window_end=window.end, counts={})
        session.add(run)
        await session.flush()
        state = {"run_id": run.id, "user_id": connection.user_id, "scopes": set(connection.granted_scopes or []),
                 "access": connection.access_token_enc, "refresh": connection.refresh_token_enc,
                 "expires": connection.token_expires_at}
    return window, state


async def _access_token(connection_id: UUID, state: dict, http: httpx.AsyncClient) -> str:
    if state["access"] and state["expires"] and state["expires"] - TOKEN_SKEW > datetime.now(timezone.utc):
        return decrypt_secret(state["access"])
    if not state["refresh"]:
        raise ReauthRequired()
    data = await oauth.refresh_access_token(http, decrypt_secret(state["refresh"]))
    async with get_db_session() as session:
        connection = await session.get(HealthConnection, connection_id)
        connection.access_token_enc = encrypt_secret(data["access_token"])
        connection.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))
        if data.get("refresh_token"):
            connection.refresh_token_enc = encrypt_secret(data["refresh_token"])
    return data["access_token"]


async def _list(client: GoogleHealthClient, data_type: str, filter: str | None) -> list[dict]:
    """Filter server-side; fall back to an unfiltered read if the filter is rejected."""
    try:
        return await client.list_points(data_type, filter=filter)
    except GoogleHealthError as exc:
        if exc.status != 400 or filter is None:
            raise
        return await client.list_points(data_type)


async def fetch_all(client: GoogleHealthClient, window: Window, scopes: set[str]) -> dict[str, Any]:
    """Read every granted data type; per-type failures are recorded, not raised."""
    granted = {key for key, scope in oauth.SCOPES.items() if scope in scopes}
    end_exclusive = window.end + timedelta(days=1)
    result: dict[str, Any] = {"days": {}, "read": set(), "errors": {}, "skipped": [], "points": {},
                              "body": [], "samples": [], "sleep": [], "workouts": [], "profile": None, "settings": None}

    async def attempt(data_type: str, scope: str, call):
        if scope not in granted:
            result["skipped"].append(data_type)
            return None
        try:
            value = await call()
        except ReauthRequired:
            raise
        except GoogleHealthError as exc:
            result["errors"][data_type] = exc.code
            return None
        result["read"].add(data_type)
        return value

    def merge(days: dict[date, dict]) -> None:
        for day, fields in days.items():
            if window.contains(day):
                result["days"].setdefault(day, {}).update(fields)

    for data_type, (scope, span) in ROLLUP_TYPES.items():
        async def rollup(data_type=data_type, span=span):
            points = []
            for start, stop in _chunks(window.start, end_exclusive, span):
                points.extend(await client.daily_rollup(data_type, start, stop))
            return points
        points = await attempt(data_type, scope, rollup)
        if points is not None:
            result["points"][data_type] = len(points)
            merge(mappers.rollup_rows(data_type, points))
    for data_type, scope in DAILY_TYPES.items():
        path = field_path(data_type)
        points = await attempt(data_type, scope, lambda data_type=data_type, path=path: _list(
            client, data_type, f'{path}.date >= "{window.start.isoformat()}" AND {path}.date <= "{window.end.isoformat()}"'))
        if points is not None:
            result["points"][data_type] = len(points)
            merge(mappers.daily_rows(data_type, points))
    for data_type, scope in {**BODY_TYPES, **SAMPLE_TYPES}.items():
        path = field_path(data_type)
        points = await attempt(data_type, scope, lambda data_type=data_type, path=path: _list(
            client, data_type, f'{path}.sample_time.physical_time >= "{_utc(window.utc_start)}" '
                               f'AND {path}.sample_time.physical_time < "{_utc(window.utc_end)}"'))
        if points is None:
            continue
        result["points"][data_type] = len(points)
        if data_type in BODY_TYPES:
            rows = mappers.body_rows(data_type, points)
            result["body"].extend(row for row in rows if window.utc_start <= row["recorded_at"] < window.utc_end)
        else:
            rows = mappers.sample_rows(data_type, points)
            result["samples"].extend(row for row in rows if window.utc_start <= row["measured_at"] < window.utc_end)
    for data_type, scope in SESSION_TYPES.items():
        bound = "civil_end_time" if data_type == "sleep" else "civil_start_time"
        points = await attempt(data_type, scope, lambda data_type=data_type, bound=bound: _list(
            client, data_type, f'{data_type}.interval.{bound} >= "{window.start.isoformat()}"'))
        if points is None:
            continue
        result["points"][data_type] = len(points)
        if data_type == "sleep":
            result["sleep"] = [row for row in mappers.sleep_rows(points, window.zone) if window.contains(row["local_date"])]
            merge({day: {"sleep_minutes": minutes} for day, minutes in mappers.main_sleep_minutes(result["sleep"]).items()})
        else:
            result["workouts"] = [row for row in mappers.workout_rows(points, window.zone) if window.contains(row["local_date"])]
    result["profile"] = await attempt("profile", "profile", client.get_profile)
    result["settings"] = await attempt("settings", "settings", client.get_settings)
    return result


async def _deactivate_missing(session, table: str, user_id: UUID, keep: list[str], column: str,
                              low: Any, high: Any) -> int:
    """Soft-delete provider records inside the window that the provider no longer returns."""
    result = await session.execute(text(f"""
        UPDATE {table} SET is_active = false, updated_at = now(), version_id = version_id + 1
        WHERE user_id = :uid AND source = :source AND is_active AND {column} >= :low AND {column} <= :high
          AND NOT (external_id = ANY(CAST(:keep AS text[])))"""),
        {"uid": user_id, "source": HEALTH_PROVIDER, "low": low, "high": high, "keep": keep})
    return result.rowcount or 0


async def store(session, user_id: UUID, window: Window, fetched: dict[str, Any]) -> dict[str, Any]:
    """Persist one fetch; each data family in a savepoint. Returns counts and storage errors."""
    counts: dict[str, Any] = {}
    errors: dict[str, str] = {}
    read = fetched["read"]

    async def guarded(name: str, write):
        try:
            async with session.begin_nested():
                counts[name] = await write()
        except Exception as exc:  # A constraint on one family must not lose the others.
            logger.warning("google_health_store_failed family=%s error=%s", name, type(exc).__name__)
            errors[name] = "storage_error"

    columns = sorted({column for data_type in read for column in TYPE_COLUMNS.get(data_type, ())})
    if columns and fetched["days"]:
        fields = (*columns, "timezone", "data_source")
        rows = [{"user_id": user_id, "local_date": day, "source": HEALTH_PROVIDER, "timezone": window.zone,
                 "data_source": {"provider": HEALTH_PROVIDER, "family": "all-sources"},
                 **{column: values.get(column, {} if column == "active_minutes_by_level" else None)
                    for column in columns}}
                for day, values in sorted(fetched["days"].items())]
        await guarded("daily_days", lambda: upsert_rows(
            session, DailyHealthSummary, rows, keys=("user_id", "local_date", "source"), fields=fields))
    if "sleep" in read:
        async def sleep():
            rows = [{"user_id": user_id, "source": HEALTH_PROVIDER, **row} for row in fetched["sleep"]]
            written = await upsert_rows(session, SleepSession, rows, keys=("user_id", "source", "external_id"),
                                        fields=SLEEP_FIELDS)
            removed = await _deactivate_missing(session, "sleep_sessions", user_id, [r["external_id"] for r in rows],
                                                "local_date", window.start, window.end)
            return {"written": written, "removed": removed}
        await guarded("sleep_sessions", sleep)
    if "exercise" in read:
        async def workouts():
            rows = [{"user_id": user_id, "source": HEALTH_PROVIDER, **row} for row in fetched["workouts"]]
            written = await upsert_rows(session, DeviceWorkout, rows, keys=("user_id", "source", "external_id"),
                                        fields=WORKOUT_FIELDS)
            removed = await _deactivate_missing(session, "device_workouts", user_id, [r["external_id"] for r in rows],
                                                "local_date", window.start, window.end)
            return {"written": written, "removed": removed}
        await guarded("device_workouts", workouts)
    sample_types = read & set(SAMPLE_TYPES)
    if sample_types:
        async def samples():
            rows = [{"user_id": user_id, "source": HEALTH_PROVIDER, **row} for row in fetched["samples"]]
            written = await upsert_rows(session, HealthSample, rows, keys=("user_id", "source", "external_id"),
                                        fields=SAMPLE_FIELDS)
            removed = 0
            if sample_types == set(SAMPLE_TYPES):
                removed = await _deactivate_missing(session, "health_samples", user_id, [r["external_id"] for r in rows],
                                                    "measured_at", window.utc_start, window.utc_end - timedelta(microseconds=1))
            return {"written": written, "removed": removed}
        await guarded("health_samples", samples)
    body_types = read & set(BODY_TYPES)
    if body_types:
        # Removals need every body type read: otherwise a weight-only read would
        # deactivate the height and body-fat samples it did not see.
        await guarded("body_metrics", lambda: BodyMetric.sync_device_samples(
            session, user_id=user_id, source=HEALTH_PROVIDER, rows=fetched["body"],
            window=(window.utc_start, window.utc_end) if body_types == set(BODY_TYPES) else None))
    return {"counts": counts, "errors": errors}


async def _run(connection_id: UUID, trigger: str | None, http: httpx.AsyncClient, today: date | None) -> dict[str, Any]:
    window, state = await _start(connection_id, trigger, today)
    try:
        access = await _access_token(connection_id, state, http)
        fetched = await fetch_all(GoogleHealthClient(access, http), window, state["scopes"])
    except ReauthRequired:
        return await _finish(connection_id, state, window, status="FAILED", error="reauth_required", reauth=True)
    except (GoogleHealthError, TokenCipherUnavailable) as exc:
        code = exc.code if isinstance(exc, GoogleHealthError) else "credential_unavailable"
        return await _finish(connection_id, state, window, status="FAILED", error=code)
    async with get_db_session() as session:
        connection = await session.get(HealthConnection, connection_id)
        if fetched["profile"] is not None or fetched["settings"] is not None:
            connection.provider_profile = {**(connection.provider_profile or {}),
                                           **mappers.provider_profile(fetched["profile"], fetched["settings"])}
            connection.timezone = mappers.provider_timezone(fetched["settings"]) or connection.timezone
        stored = await store(session, state["user_id"], window, fetched)
    errors = {**fetched["errors"], **stored["errors"]}
    status = "FAILED" if not fetched["read"] else "PARTIAL" if errors else "SUCCEEDED"
    counts = {**stored["counts"], "points": fetched["points"], "skipped": fetched["skipped"], "errors": errors}
    return await _finish(connection_id, state, window, status=status, error=None if status != "FAILED" else "no_data_read",
                         counts=counts)


async def _finish(connection_id: UUID, state: dict, window: Window, *, status: str, error: str | None,
                  counts: dict | None = None, reauth: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        connection = await session.get(HealthConnection, connection_id)
        run = await session.get(HealthSyncRun, state["run_id"])
        run.status, run.error_code, run.finished_at = status, error, now
        run.counts = jsonable(counts or {})
        connection.last_sync_at = now
        connection.last_error_code = error
        if reauth:
            connection.status = "NEEDS_REAUTH"
            connection.next_sync_at = None
        else:
            connection.next_sync_at = now + timedelta(minutes=settings.GOOGLE_HEALTH_SYNC_INTERVAL_MINUTES)
        if status != "FAILED":
            connection.last_success_at = now
            connection.sync_cursor = {**(connection.sync_cursor or {}), "last_window_end": window.end.isoformat()}
    logger.info("google_health_sync status=%s error=%s", status, error)
    return {"status": status, "error": error, "window": [window.start.isoformat(), window.end.isoformat()],
            "counts": jsonable(counts or {})}


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in (sorted(value) if isinstance(value, set) else value)]
    return value
