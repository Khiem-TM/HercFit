"""Đồng bộ theo từng loại, có lease và fence, cho một kết nối Google Health.

1. Lấy lease (SKIP LOCKED): lần lấy tăng `lease_epoch`, chính là fencing token.
   Heartbeat gia hạn lease suốt lượt chạy; mất lease thì dừng lượt chạy.
   Không giữ transaction nào trong lúc gọi HTTP.
2. Làm mới access token dưới advisory lock theo từng kết nối, đọc lại
   token sau khi lấy khoá để các lượt chạy đồng thời chỉ làm mới một lần. invalid_grant đánh dấu
   kết nối NEEDS_REAUTH (refresh token ở chế độ Testing hết hạn sau 7 ngày).
3. Đọc từng loại dữ liệu người dùng đã cấp và registry đã bật, qua
   filter đã mô tả cho dạng của nó (ingest/reads.py) và các phép chiếu tường minh.
   Mỗi loại kết thúc COMPLETE, INCOMPLETE (hết ngân sách trang), NOT_GRANTED,
   ERROR hoặc SKIPPED; một loại không bao giờ che hay làm mất loại khác.
4. Lưu trong một transaction đã fence, mỗi họ dữ liệu một savepoint. Loại chưa
   được đọc trọn vẹn và sạch sẽ thì không bị ghi đè (không có cột None) và
   không bao giờ xoá gì. Bản ghi vắng mặt trong một cửa sổ trọn vẹn, sạch sẽ thì bị
   vô hiệu hoá.
5. Mỗi loại giữ cursor riêng (`sync_cursor.types`); chỉ COMPLETE mới đẩy nó lên.

Pipeline job (M3+) dùng lại các lần đọc và phép chiếu; module này vẫn là
đường trong tiến trình cho đến khi GH_INGEST_V2=primary.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from core.crypto import TokenCipherUnavailable
from core.database import get_db_session
from core.settings import settings
from domains.body.models.body_metrics import BodyMetric
from domains.health_records.models.device_records import (
    SAMPLE_FIELDS, SLEEP_FIELDS, WORKOUT_FIELDS, DailyHealthSummary, DeviceWorkout, HealthSample, SleepSession,
    upsert_rows,
)
from domains.health_records.schemas.health import HEALTH_PROVIDER
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, day_bounds
from integrations.google_health import projections, tokens
from integrations.google_health.adapters import adapter_for
from integrations.google_health.adapters.base import BAD_TYPE
from integrations.google_health.client import (
    PERMISSION, Fetch, GoogleHealthClient, GoogleHealthError, ReauthRequired,
)
from integrations.google_health.contract import scopes as contract_scopes
from integrations.google_health.contract.registry import Op, runtime_enabled, spec
from integrations.google_health.ingest import reads
from integrations.google_health.models import HealthConnection, HealthSyncRun

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=3)
HEARTBEAT_SECONDS = 60
OVERLAP_DAYS = 3
TOKEN_SKEW = timedelta(seconds=60)

# Những gì sync trong tiến trình lưu, theo họ dữ liệu đích.
ROLLUP_TYPES = ("steps", "distance", "floors", "active-minutes", "active-zone-minutes", "total-calories",
                "active-energy-burned", "heart-rate", "hydration-log")
DAILY_TYPES = ("daily-resting-heart-rate", "daily-heart-rate-variability", "daily-oxygen-saturation",
               "daily-respiratory-rate", "daily-sleep-temperature-derivations", "daily-vo2-max")
BODY_TYPES = tuple(projections.BODY)
SAMPLE_TYPES = tuple(projections.SAMPLES)
SESSION_TYPES = ("sleep", "exercise")
SYNC_TYPES = (*ROLLUP_TYPES, *DAILY_TYPES, *BODY_TYPES, *SAMPLE_TYPES, *SESSION_TYPES)
# Các cột theo ngày mà mỗi loại sở hữu; một cột chỉ được ghi khi loại của nó đã được đọc trọn vẹn.
TYPE_COLUMNS: dict[str, tuple[str, ...]] = {
    "steps": ("steps",), "distance": ("distance_m",), "floors": ("floors",),
    "active-minutes": ("active_minutes", "active_minutes_by_level"), "active-zone-minutes": ("active_zone_minutes",),
    "total-calories": ("total_kcal",), "active-energy-burned": ("active_kcal",),
    "heart-rate": ("hr_avg_bpm", "hr_min_bpm", "hr_max_bpm"), "hydration-log": ("hydration_ml",),
    "daily-resting-heart-rate": ("resting_hr_bpm",), "daily-heart-rate-variability": ("hrv_ms",),
    "daily-oxygen-saturation": ("spo2_avg_pct",), "daily-respiratory-rate": ("respiratory_rate",),
    "daily-sleep-temperature-derivations": ("skin_temp_delta_c",), "daily-vo2-max": ("vo2_max",),
    "sleep": ("sleep_minutes",),
}
COMPLETE, INCOMPLETE, NOT_GRANTED, ERROR, SKIPPED = "COMPLETE", "INCOMPLETE", "NOT_GRANTED", "ERROR", "SKIPPED"


class FencedOut(Exception):
    """Lease hoặc thế hệ kết nối đã chuyển đi: lượt chạy này không được ghi."""


class Window:
    def __init__(self, start: date, end: date, zone: str):
        self.start, self.end, self.zone = start, end, zone
        self.utc_start, self.utc_end = day_bounds(start, end, zone)

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)

    def contains(self, day: date | None) -> bool:
        return day is not None and self.start <= day <= self.end


@dataclass
class TypeRead:
    data_type: str
    status: str = SKIPPED
    error_code: str | None = None
    error_class: str | None = None
    points: int = 0
    pages: int = 0
    rejected: int = 0      # các điểm mà adapter không tin được giá trị hay thời điểm
    unknown: int = 0       # các điểm có trường mới hơn ảnh chụp discovery
    seen: set[str] = field(default_factory=set)

    @property
    def clean(self) -> bool:
        return self.status == COMPLETE and self.rejected == 0

    def summary(self) -> dict[str, Any]:
        return {"status": self.status, "error": self.error_code, "points": self.points, "pages": self.pages,
                "rejected": self.rejected, "unknown": self.unknown}


@dataclass
class Lease:
    connection_id: UUID
    token: UUID
    epoch: int
    generation: int
    lost: bool = False


def _cursor(connection: HealthConnection) -> dict[str, Any]:
    return dict(connection.sync_cursor or {})


def type_cursor(connection: HealthConnection, data_type: str) -> date | None:
    cursor = _cursor(connection)
    entry = (cursor.get("types") or {}).get(data_type) or {}
    value = entry.get("complete_through") or (cursor.get("last_window_end") if connection.last_success_at else None)
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def sync_window(connection: HealthConnection, today: date) -> Window:
    """Điền dữ liệu ở lượt chạy đầu; sau đó đọc lại từ cursor của loại chậm nhất trừ đi một khoảng chồng lấn."""
    zone = connection.timezone or DEFAULT_TIMEZONE
    earliest = today - timedelta(days=settings.GOOGLE_HEALTH_BACKFILL_DAYS - 1)
    known = [value for value in (type_cursor(connection, data_type) for data_type in SYNC_TYPES) if value]
    if connection.last_success_at is None or not known:
        return Window(earliest, today, zone)
    return Window(max(earliest, min(min(known), today) - timedelta(days=OVERLAP_DAYS)), today, zone)


# ------------------------------------------------------------------------------------------- đọc
async def _read(item_type: str, coroutine) -> tuple[TypeRead, Fetch | None]:
    result = TypeRead(item_type)
    try:
        fetch = await coroutine
    except ReauthRequired:
        raise
    except GoogleHealthError as exc:
        result.status = NOT_GRANTED if exc.error_class == PERMISSION else ERROR
        result.error_code, result.error_class = exc.code, exc.error_class
        return result, None
    result.status = COMPLETE if fetch.complete else INCOMPLETE
    result.points, result.pages = len(fetch.points), fetch.pages
    return result, fetch


def _enabled(data_type: str, op: Op, granted: list[str] | set[str]) -> str | None:
    """None khi loại được phép đọc lúc này, ngược lại là lý do bỏ qua."""
    item = spec(data_type)
    if not runtime_enabled(data_type, op, verified=settings.verified_capabilities,
                           api_version="v4" if "v4" in item.api_versions else "v4beta"):
        return SKIPPED
    if not contract_scopes.can_read(item.scope_group, granted):
        return NOT_GRANTED
    return None


async def fetch_all(client: GoogleHealthClient, window: Window, granted: set[str] | list[str]) -> dict[str, Any]:
    """Đọc mọi loại đã bật và đã cấp; kết quả từng loại được ghi lại, không bao giờ ném lỗi (trừ khi cần uỷ quyền lại)."""
    v4beta = set(settings.GH_V4BETA_TYPES)
    result: dict[str, Any] = {"days": {}, "types": {}, "body": [], "samples": [], "sleep": [], "workouts": [],
                              "profile": None, "settings": None, "identity": None}
    types: dict[str, TypeRead] = result["types"]

    def merge(day: date | None, columns: dict[str, Any]) -> None:
        if window.contains(day):
            projections.merge_days(result["days"], day, columns)

    def parsed_points(data_type: str, fetch: Fetch, read: TypeRead, *, rollup: bool = False):
        parser = adapter_for(data_type, v4beta)
        from integrations.google_health.export.selfsource import written_by_us

        for raw in fetch.points:
            if not rollup and written_by_us(raw.get("dataSource")):
                continue  # dữ liệu HercFit tự xuất quay về: bản ghi cục bộ đã tồn tại
            parsed = parser.parse_rollup(data_type, raw, daily=True) if rollup else parser.parse_point(data_type, raw)
            if any(code == BAD_TYPE for code in parsed.quality.values()):
                read.rejected += 1
            if parsed.unknown_paths:
                read.unknown += 1
            yield parsed

    for data_type in ROLLUP_TYPES:
        reason = _enabled(data_type, Op.DAILY_ROLLUP, granted)
        if reason:
            types[data_type] = TypeRead(data_type, reason)
            continue
        plan = reads.plan(data_type, rollup=True)

        async def rollup(data_type=data_type, plan=plan) -> Fetch:
            total = Fetch()
            for start, stop in reads.chunks(window.start, window.end_exclusive, plan.chunk_days):
                part = await client.daily_rollup_all(data_type, start, stop, page_size=plan.page_size,
                                                     max_pages=reads.MAX_PAGES)
                total.points.extend(part.points)
                total.pages += part.pages
                if not part.complete:
                    total.complete, total.next_token = False, part.next_token
                    break
            return total
        read, fetch = await _read(data_type, rollup())
        types[data_type] = read
        if fetch is not None:
            for parsed in parsed_points(data_type, fetch, read, rollup=True):
                merge(parsed.time.civil_date, projections.rollup_columns(parsed))

    async def listed(data_type: str) -> tuple[TypeRead, Fetch | None]:
        reason = _enabled(data_type, Op.LIST, granted)
        if reason:
            return TypeRead(data_type, reason), None
        plan = reads.plan(data_type, rollup=False)
        return await _read(data_type, client.list_all(
            data_type, filter=reads.list_filter(plan, window.start, window.end_exclusive),
            page_size=plan.page_size, max_pages=reads.MAX_PAGES))

    for data_type in DAILY_TYPES:
        read, fetch = await listed(data_type)
        types[data_type] = read
        if fetch is not None:
            for parsed in parsed_points(data_type, fetch, read):
                merge(parsed.time.civil_date, projections.daily_columns(parsed))
    for data_type in (*BODY_TYPES, *SAMPLE_TYPES):
        read, fetch = await listed(data_type)
        types[data_type] = read
        if fetch is None:
            continue
        for parsed in parsed_points(data_type, fetch, read):
            read.seen.add(projections.external_id(parsed, parsed.time.physical_start))
            if not window.contains(parsed.time.civil_date):
                continue
            row = projections.body_row(parsed) if data_type in BODY_TYPES else projections.sample_row(parsed)
            if row is not None:
                result["body" if data_type in BODY_TYPES else "samples"].append(row)
    for data_type in SESSION_TYPES:
        read, fetch = await listed(data_type)
        types[data_type] = read
        if fetch is None:
            continue
        for parsed in parsed_points(data_type, fetch, read):
            read.seen.add(projections.external_id(parsed, parsed.time.physical_start))
            row = (projections.sleep_row if data_type == "sleep" else projections.workout_row)(parsed, window.zone)
            if row is not None and window.contains(row["local_date"]):
                result["sleep" if data_type == "sleep" else "workouts"].append(row)
        if data_type == "sleep" and read.status == COMPLETE:
            for day, minutes in projections.main_sleep_minutes(result["sleep"]).items():
                merge(day, {"sleep_minutes": minutes})

    for key, group, call in (("profile", "profile", client.get_profile), ("settings", "settings", client.get_settings)):
        if contract_scopes.can_read(group, granted):
            with suppress(GoogleHealthError):
                result[key] = await call()
    return result


# ------------------------------------------------------------------------------------------- lưu
async def _deactivate_missing(session, table: str, user_id: UUID, keep: list[str], column: str,
                              low: Any, high: Any) -> int:
    """Xoá mềm các bản ghi nhà cung cấp trong cửa sổ mà nhà cung cấp không còn trả về."""
    outcome = await session.execute(text(f"""
        UPDATE {table} SET is_active = false, updated_at = now(), version_id = version_id + 1
        WHERE user_id = :uid AND source = :source AND is_active AND {column} >= :low AND {column} <= :high
          AND NOT (external_id = ANY(CAST(:keep AS text[])))"""),
        {"uid": user_id, "source": HEALTH_PROVIDER, "low": low, "high": high, "keep": keep})
    return outcome.rowcount or 0


def _complete(fetched: dict[str, Any]) -> set[str]:
    types = fetched.get("types")
    if types is None:  # bên gọi có từ trước khi có kết quả theo loại coi mọi loại đã đọc là trọn vẹn
        return set(fetched.get("read") or ())
    return {name for name, read in types.items() if read.status == COMPLETE}


def _clean(fetched: dict[str, Any]) -> set[str]:
    types = fetched.get("types")
    if types is None:
        return set(fetched.get("read") or ())
    return {name for name, read in types.items() if read.clean}


async def store(session, user_id: UUID, window: Window, fetched: dict[str, Any]) -> dict[str, Any]:
    """Lưu một lần fetch; mỗi họ dữ liệu một savepoint. Trả về số đếm và lỗi lưu trữ."""
    counts: dict[str, Any] = {}
    errors: dict[str, str] = {}
    complete, clean = _complete(fetched), _clean(fetched)

    async def guarded(name: str, write):
        try:
            async with session.begin_nested():
                counts[name] = await write()
        except FencedOut:
            raise
        except Exception as exc:  # Ràng buộc trên một họ dữ liệu không được làm mất các họ khác.
            logger.warning("google_health_store_failed family=%s error=%s", name, type(exc).__name__)
            errors[name] = "storage_error"

    def seen(data_type: str) -> set[str]:
        types = fetched.get("types") or {}
        return types[data_type].seen if data_type in types else set()

    columns = sorted({column for data_type in complete for column in TYPE_COLUMNS.get(data_type, ())})
    if columns and fetched["days"]:
        fields = (*columns, "timezone", "data_source")
        rows = [{"user_id": user_id, "local_date": day, "source": HEALTH_PROVIDER, "timezone": window.zone,
                 "data_source": {"provider": HEALTH_PROVIDER, "family": "all-sources"},
                 **{column: values.get(column, {} if column == "active_minutes_by_level" else None)
                    for column in columns}}
                for day, values in sorted(fetched["days"].items())]
        await guarded("daily_days", lambda: upsert_rows(
            session, DailyHealthSummary, rows, keys=("user_id", "local_date", "source"), fields=fields))

    async def sessions(name: str, model, rows_key: str, data_type: str, fields: tuple[str, ...]):
        rows = [{"user_id": user_id, "source": HEALTH_PROVIDER, **{k: v for k, v in row.items() if k in fields
                                                                  or k == "external_id"}}
                for row in fetched[rows_key]]
        written = await upsert_rows(session, model, rows, keys=("user_id", "source", "external_id"), fields=fields)
        removed = 0
        if data_type in clean:
            keep = sorted({row["external_id"] for row in rows} | seen(data_type))
            removed = await _deactivate_missing(session, name, user_id, keep, "local_date", window.start, window.end)
        return {"written": written, "removed": removed}

    if "sleep" in complete:
        await guarded("sleep_sessions", lambda: sessions("sleep_sessions", SleepSession, "sleep", "sleep", SLEEP_FIELDS))
    if "exercise" in complete:
        await guarded("device_workouts", lambda: sessions("device_workouts", DeviceWorkout, "workouts", "exercise",
                                                          WORKOUT_FIELDS))
    sample_types = complete & set(SAMPLE_TYPES)
    if sample_types:
        async def samples():
            rows = [{"user_id": user_id, "source": HEALTH_PROVIDER, **row} for row in fetched["samples"]
                    if any(row["sample_type"] == projections.SAMPLES[t][0] for t in sample_types)]
            written = await upsert_rows(session, HealthSample, rows, keys=("user_id", "source", "external_id"),
                                        fields=SAMPLE_FIELDS)
            removed = 0
            if set(SAMPLE_TYPES) <= clean:
                keep = sorted({row["external_id"] for row in rows} | set().union(*(seen(t) for t in SAMPLE_TYPES)))
                removed = await _deactivate_missing(session, "health_samples", user_id, keep, "measured_at",
                                                    window.utc_start, window.utc_end - timedelta(microseconds=1))
            return {"written": written, "removed": removed}
        await guarded("health_samples", samples)
    body_types = complete & set(BODY_TYPES)
    if body_types:
        # Việc xoá cần mọi loại số đo cơ thể được đọc trọn vẹn và sạch sẽ: nếu không, một
        # lần đọc chỉ có cân nặng sẽ vô hiệu hoá các mẫu chiều cao và mỡ cơ thể mà nó không thấy.
        await guarded("body_metrics", lambda: BodyMetric.sync_device_samples(
            session, user_id=user_id, source=HEALTH_PROVIDER, rows=fetched["body"],
            window=(window.utc_start, window.utc_end) if set(BODY_TYPES) <= clean else None))
    return {"counts": counts, "errors": errors}


# ------------------------------------------------------------------------------------------- lease
async def _claim(session, connection_id: UUID | None, token: UUID) -> Lease | None:
    """Lease một kết nối: một kết nối cụ thể (sync thủ công) hoặc kết nối quá hạn lâu nhất."""
    selector = "id = :id" if connection_id else "next_sync_at <= now()"
    row = (await session.execute(text(f"""
        UPDATE health_connections SET lease_token = :token, lease_until = now() + make_interval(secs => :lease),
               lease_epoch = lease_epoch + 1
        WHERE id = (SELECT id FROM health_connections
                    WHERE {selector} AND status = 'ACTIVE' AND is_active
                      AND (lease_until IS NULL OR lease_until < now())
                    ORDER BY next_sync_at NULLS FIRST LIMIT 1 FOR UPDATE SKIP LOCKED)
        RETURNING id, lease_epoch, generation"""),
        {"id": connection_id, "token": token, "lease": LEASE.total_seconds()})).first()
    return Lease(row[0], token, row[1], row[2]) if row else None


async def fence(session, lease: Lease) -> None:
    """Gọi đầu tiên trong mọi transaction ghi thay mặt một lượt chạy."""
    row = (await session.execute(text(
        "SELECT 1 FROM health_connections WHERE id = :id AND lease_token = :token AND lease_epoch = :epoch "
        "AND generation = :generation AND status = 'ACTIVE' FOR UPDATE"),
        {"id": lease.connection_id, "token": lease.token, "epoch": lease.epoch,
         "generation": lease.generation})).first()
    if row is None:
        lease.lost = True
        raise FencedOut()


async def _heartbeat(lease: Lease) -> None:
    while not lease.lost:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        async with get_db_session() as session:
            row = (await session.execute(text(
                "UPDATE health_connections SET lease_until = now() + make_interval(secs => :lease) "
                "WHERE id = :id AND lease_token = :token AND lease_epoch = :epoch RETURNING 1"),
                {"id": lease.connection_id, "token": lease.token, "epoch": lease.epoch,
                 "lease": LEASE.total_seconds()})).first()
        if row is None:
            lease.lost = True
            logger.warning("google_health_lease_lost")


async def _release(lease: Lease) -> None:
    async with get_db_session() as session:
        await session.execute(text("UPDATE health_connections SET lease_token = NULL, lease_until = NULL "
                                   "WHERE id = :id AND lease_token = :token AND lease_epoch = :epoch"),
                              {"id": lease.connection_id, "token": lease.token, "epoch": lease.epoch})


async def sync_connection(connection_id: UUID | None = None, *, trigger: str | None = None,
                          http: httpx.AsyncClient | None = None, today: date | None = None) -> dict[str, Any]:
    """Đồng bộ một kết nối (hoặc kết nối quá hạn lâu nhất); trả về bản tóm tắt lượt chạy."""
    async with get_db_session() as session:
        lease = await _claim(session, connection_id, uuid4())
    if lease is None:
        return {"status": "busy" if connection_id else "idle"}
    heartbeat = asyncio.create_task(_heartbeat(lease))
    try:
        if http is not None:
            return await _run(lease, trigger, http, today)
        async with httpx.AsyncClient() as client:
            return await _run(lease, trigger, client, today)
    except FencedOut:
        logger.warning("google_health_sync_fenced_out")
        return {"status": "FENCED_OUT"}
    finally:
        lease.lost = True
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await _release(lease)


async def _start(lease: Lease, trigger: str | None, today: date | None):
    async with get_db_session() as session:
        await fence(session, lease)
        connection = await session.get(HealthConnection, lease.connection_id)
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
                 "expires": connection.token_expires_at, "health_user_id": connection.health_user_id}
    return window, state


async def _access_token(lease: Lease, state: dict, http: httpx.AsyncClient) -> str:
    async def check(session):
        await fence(session, lease)

    token, granted = await tokens.access_token(lease.connection_id, http, check=check)
    state["scopes"] = set(granted)
    return token


async def _run(lease: Lease, trigger: str | None, http: httpx.AsyncClient, today: date | None) -> dict[str, Any]:
    window, state = await _start(lease, trigger, today)
    try:
        access = await _access_token(lease, state, http)
        client = GoogleHealthClient(access, http)
        if not state["health_user_id"]:
            with suppress(GoogleHealthError):
                state["identity"] = await client.get_identity()
        fetched = await fetch_all(client, window, state["scopes"])
    except ReauthRequired:
        return await _finish(lease, state, window, status="FAILED", error="reauth_required", reauth=True)
    except (GoogleHealthError, TokenCipherUnavailable) as exc:
        code = exc.code if isinstance(exc, GoogleHealthError) else "credential_unavailable"
        return await _finish(lease, state, window, status="FAILED", error=code)
    if lease.lost:
        raise FencedOut()
    async with get_db_session() as session:
        await fence(session, lease)
        connection = await session.get(HealthConnection, lease.connection_id)
        if fetched["profile"] is not None or fetched["settings"] is not None:
            connection.provider_profile = {**(connection.provider_profile or {}),
                                           **projections.provider_profile(fetched["profile"], fetched["settings"])}
            connection.timezone = projections.provider_timezone(fetched["settings"]) or connection.timezone
        identity = state.get("identity") or {}
        if identity.get("healthUserId") and not connection.health_user_id:
            connection.health_user_id = str(identity["healthUserId"])[:255]
        from integrations.google_health.export.capture import mark_import

        await mark_import(session)
        stored = await store(session, state["user_id"], window, fetched)
    types: dict[str, TypeRead] = fetched["types"]
    attempted = [read for read in types.values() if read.status not in (SKIPPED, NOT_GRANTED)]
    failed = {name: read.error_code or read.status for name, read in types.items() if read.status in (ERROR, INCOMPLETE)}
    errors = {**failed, **stored["errors"]}
    succeeded = [read for read in attempted if read.status == COMPLETE]
    status = "FAILED" if attempted and not succeeded else "PARTIAL" if errors else "SUCCEEDED"
    if not attempted:
        status = "FAILED"
    counts = {**stored["counts"], "types": {name: read.summary() for name, read in types.items()},
              "skipped": sorted(name for name, read in types.items() if read.status in (SKIPPED, NOT_GRANTED)),
              "errors": errors}
    error = None if status != "FAILED" else ("no_data_read" if not attempted else "all_types_failed")
    return await _finish(lease, state, window, status=status, error=error, counts=counts, types=types,
                         stored_errors=stored["errors"])


def _advance(cursor: dict[str, Any], window: Window, types: dict[str, TypeRead], stored_errors: dict[str, str],
             now: datetime) -> dict[str, Any]:
    family_of = {**{t: "daily_days" for t in (*ROLLUP_TYPES, *DAILY_TYPES)}, "sleep": "sleep_sessions",
                 "exercise": "device_workouts", **{t: "body_metrics" for t in BODY_TYPES},
                 **{t: "health_samples" for t in SAMPLE_TYPES}}
    entries = dict(cursor.get("types") or {})
    for name, read in types.items():
        entry = dict(entries.get(name) or {})
        stored_ok = family_of.get(name) not in stored_errors
        if read.status == COMPLETE and stored_ok:
            entry["complete_through"] = window.end.isoformat()
        entry.update(status=read.status if stored_ok else ERROR, error=read.error_code, at=now.isoformat())
        entries[name] = entry
    done = [entry["complete_through"] for name, entry in entries.items()
            if name in SYNC_TYPES and entry.get("complete_through") and types.get(name)
            and types[name].status not in (SKIPPED, NOT_GRANTED)]
    result = {**cursor, "types": entries}
    if done:
        result["last_window_end"] = min(done)
    return result


async def _finish(lease: Lease, state: dict, window: Window, *, status: str, error: str | None,
                  counts: dict | None = None, reauth: bool = False, types: dict[str, TypeRead] | None = None,
                  stored_errors: dict[str, str] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        await fence(session, lease)
        connection = await session.get(HealthConnection, lease.connection_id)
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
        if types:
            connection.sync_cursor = _advance(_cursor(connection), window, types, stored_errors or {}, now)
    logger.info("google_health_sync status=%s error=%s", status, error)
    return {"status": status, "error": error, "window": [window.start.isoformat(), window.end.isoformat()],
            "counts": jsonable(counts or {})}


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in (sorted(value) if isinstance(value, set) else value)]
    if isinstance(value, TypeRead):
        return value.summary()
    return value
