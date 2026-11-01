"""Handler job Google Health (do workers/ chạy, xếp hàng trong bảng jobs).

GH_ONBOARD         lập kế hoạch lần nhập đầu: trước tiên 30 ngày tổng hợp, phiên và
                   bản ghi; rồi 90 ngày chuỗi dày (mỗi job một ngày UTC,
                   lùi dần); rồi tới 2 năm tổng hợp và
                   metadata phiên, ở độ ưu tiên thấp.
GH_FETCH_WINDOW    đọc một loại dữ liệu cho một cửa sổ, từng trang. Mỗi trang được
                   lưu tạm cùng page token kế tiếp trong một transaction đã fence, nên
                   khi sập sẽ tiếp tục đúng chỗ dừng. Hết ngân sách trang thì job
                   nhường slot và tiếp tục sau. Chỉ cửa sổ trọn vẹn mới quét bản ghi bị xoá,
                   áp vào bảng nghiệp vụ (chế độ primary) và đẩy cursor.
GH_RECONCILE       mỗi 6 giờ: 3 ngày gần nhất của mọi loại đã bật.
GH_REVERIFY        một lát 7 ngày xoay vòng của lịch sử cũ hơn, để bắt các lần sửa muộn.
GH_WEBHOOK_ROUTE   định tuyến thông báo đã kiểm chứng thành các lần fetch gộp.
GH_IDENTITY_REFRESH health user id, thiết bị đã ghép, hồ sơ và cài đặt.
SHADOW_COMPARE     chế độ shadow: những gì chế độ primary sẽ đổi, lưu thành diff.
RETENTION_SWEEP    xoá chi tiết quá hạn lưu (HEALTH_RETENTION_ENFORCE).
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from core.database import get_db_session
from core.jobs import queue
from core.jobs.queue import Job
from core.settings import settings
from domains.health_records.models.clinical import PairedDevice
from domains.health_records.models.sources import HealthSeriesChunk
from domains.shared.events import publish
from domains.shared.models.basemodel import uuid7
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE
from integrations.google_health import projections, tokens
from integrations.google_health.adapters import adapter_for, api_version_for
from integrations.google_health.adapters.base import BAD_TYPE
from integrations.google_health.client import PERMISSION, GoogleHealthClient, GoogleHealthError, Page
from integrations.google_health.contract import scopes as contract_scopes
from integrations.google_health.contract.registry import (
    DATA_TYPES, DISCOVERY_REVISION, Kind, Op, Retention, runtime_enabled, spec,
)
from integrations.google_health.ingest import apply as applying
from integrations.google_health.ingest import reads, series, stage
from integrations.google_health.models import HealthConnection

logger = logging.getLogger(__name__)
ROLLUP, POINTS, SERIES = "rollup", "points", "series"
RECENT_DAYS = 30
DETAIL_DAYS = 90
HISTORY_DAYS = 730
RECONCILE_DAYS = 3
REVERIFY_SLICE = 7
HISTORY_SPAN = 90
PRIORITY = {"recent": 80, "reconcile": 75, "webhook": 90, "detail": 40, "history": 20, "reverify": 10}
# Các rollup nuôi cột của daily_health_summaries.
ROLLUP_TYPES = frozenset({"steps", "distance", "floors", "active-minutes", "active-zone-minutes", "total-calories",
                          "active-energy-burned", "heart-rate", "hydration-log"})


class ConnectionChanged(Exception):
    """Đã ngắt kết nối, uỷ quyền lại hoặc kết nối lại kể từ khi job được xếp hàng."""


@dataclass
class Context:
    job: Job
    http: httpx.AsyncClient


# ------------------------------------------------------------------------------------------- lập kế hoạch
def modes(data_type: str) -> list[str]:
    """Cách một loại được nhập: rollup (cột theo ngày), points (bản ghi), series (chunk nén)."""
    item = spec(data_type)
    result = []
    if data_type in ROLLUP_TYPES and Op.DAILY_ROLLUP in item.read_ops:
        result.append(ROLLUP)
    if Op.LIST in item.read_ops and item.kind is not Kind.CATALOG:
        result.append(SERIES if item.family == "series" else POINTS)
    return result


def enabled_types(granted: list[str] | set[str]) -> list[str]:
    v4beta = set(settings.GH_V4BETA_TYPES)
    names = []
    for data_type, item in DATA_TYPES.items():
        version = api_version_for(data_type, v4beta)
        if not version or not item.readable:
            continue
        op = Op.LIST if Op.LIST in item.read_ops else Op.DAILY_ROLLUP
        if not runtime_enabled(data_type, op, verified=settings.verified_capabilities, api_version=version):
            continue
        if contract_scopes.can_read(item.scope_group, granted):
            names.append(data_type)
    return names


def horizon(data_type: str, mode: str) -> int:
    if mode == SERIES or spec(data_type).retention is Retention.DETAIL_90D:
        return DETAIL_DAYS
    return HISTORY_DAYS


async def enqueue_fetch(session, connection: HealthConnection, data_type: str, mode: str, start: date, end: date, *,
                        priority: int, walk_back_to: date | None = None, operation_id: UUID | None = None,
                        reason: str = "scheduled") -> UUID | None:
    return await queue.enqueue(
        session, "GH_FETCH_WINDOW", dedupe_key=f"fetch:{connection.id}:{data_type}:{mode}:{start}:{end}",
        user_id=connection.user_id, connection_id=connection.id, data_type=data_type, window_start=start,
        window_end=end, priority=priority, connection_generation=connection.generation, operation_id=operation_id,
        payload={"mode": mode, "walk_back_to": walk_back_to.isoformat() if walk_back_to else None, "reason": reason})


def today_for(connection: HealthConnection) -> date:
    return datetime.now(ZoneInfo(connection.timezone or DEFAULT_TIMEZONE)).date()


async def plan_recent(session, connection: HealthConnection, days: int, *, priority: int, reason: str,
                      operation_id: UUID | None = None, walk_back: bool = False) -> int:
    """Các job fetch cho `days` ngày gần nhất của mọi loại đã bật (series: mỗi job một ngày UTC)."""
    today = today_for(connection)
    count = 0
    for data_type in enabled_types(connection.granted_scopes or []):
        for mode in modes(data_type):
            if mode == SERIES:
                utc_today = datetime.now(timezone.utc).date()
                limit = utc_today - timedelta(days=horizon(data_type, mode) - 1) if walk_back else None
                for offset in range(min(days, 2) if not walk_back else 1):
                    day = utc_today - timedelta(days=offset)
                    count += bool(await enqueue_fetch(
                        session, connection, data_type, mode, day, day, operation_id=operation_id, reason=reason,
                        priority=PRIORITY["detail"] if walk_back else priority, walk_back_to=limit))
                continue
            start = today - timedelta(days=days - 1)
            limit = today - timedelta(days=horizon(data_type, mode) - 1) if walk_back else None
            count += bool(await enqueue_fetch(session, connection, data_type, mode, start, today, priority=priority,
                                              walk_back_to=limit, operation_id=operation_id, reason=reason))
    return count


# ------------------------------------------------------------------------------------------- hàm hỗ trợ
async def _connection(session, job: Job, *, lock: bool = False) -> HealthConnection:
    query = select(HealthConnection).where(HealthConnection.id == job.connection_id)
    if lock:
        query = query.with_for_update(read=True)
    connection = (await session.execute(query)).scalar_one_or_none()
    if (connection is None or connection.status != "ACTIVE" or not connection.is_active
            or (job.connection_generation is not None and connection.generation != job.connection_generation)):
        raise ConnectionChanged()
    return connection


@asynccontextmanager
async def fenced(job: Job):
    """Một transaction trong đó job này vẫn sở hữu lease và thế hệ kết nối của nó vẫn là hiện hành."""
    async with get_db_session() as session:
        await queue.fence(session, job)
        if job.connection_id is not None:
            await _connection(session, job, lock=True)
        yield session


async def _client(ctx: Context, connection: HealthConnection, data_type: str | None = None) -> GoogleHealthClient:
    job = ctx.job

    async def check(session):
        await queue.fence(session, job)
        await _connection(session, job, lock=True)

    access, _granted = await tokens.access_token(connection.id, ctx.http, check=check)

    async def quota():
        from core.jobs.quota import acquire
        await acquire([(f"gh:user:{connection.id}", settings.GH_USER_RPM), ("gh:project", settings.GH_PROJECT_RPM)])

    client = GoogleHealthClient(access, ctx.http, on_request=quota)
    if data_type is not None:
        version = api_version_for(data_type, set(settings.GH_V4BETA_TYPES))
        if version and version != "v4":
            client = client.for_version(version)
    return client


async def _cursor(session, connection: HealthConnection, data_type: str, *, status: str, start: date | None = None,
                  end: date | None = None, error: str | None = None) -> None:
    await session.execute(text("""
        INSERT INTO sync_cursors AS c (connection_id, data_type, source_family, complete_through, earliest_complete,
                                       status, error_code, schema_revision, generation, updated_at)
        VALUES (:connection, :data_type, 'all-sources', :end, :start, :status, :error, :revision, :generation, now())
        ON CONFLICT (connection_id, data_type, source_family) DO UPDATE SET
            complete_through = GREATEST(c.complete_through, EXCLUDED.complete_through),
            earliest_complete = LEAST(c.earliest_complete, EXCLUDED.earliest_complete),
            status = EXCLUDED.status, error_code = EXCLUDED.error_code, schema_revision = EXCLUDED.schema_revision,
            generation = EXCLUDED.generation, updated_at = now()"""),
        {"connection": connection.id, "data_type": data_type, "start": start, "end": end, "status": status,
         "error": error, "revision": DISCOVERY_REVISION, "generation": connection.generation})


# ------------------------------------------------------------------------------------------- handler
async def onboard(ctx: Context) -> None:
    async with fenced(ctx.job) as session:
        connection = await _connection(session, ctx.job)
        count = await plan_recent(session, connection, RECENT_DAYS, priority=PRIORITY["recent"], reason="onboard",
                                  walk_back=False, operation_id=ctx.job.operation_id)
        # Chi tiết dày lùi dần từng ngày (90 ngày); tổng hợp và bản ghi lùi theo cửa sổ 90 ngày.
        today = today_for(connection)
        for data_type in enabled_types(connection.granted_scopes or []):
            for mode in modes(data_type):
                if mode == SERIES:
                    utc_today = datetime.now(timezone.utc).date()
                    day = utc_today - timedelta(days=1)
                    count += bool(await enqueue_fetch(
                        session, connection, data_type, mode, day, day, priority=PRIORITY["detail"], reason="onboard",
                        walk_back_to=utc_today - timedelta(days=DETAIL_DAYS - 1)))
                    continue
                limit = today - timedelta(days=horizon(data_type, mode) - 1)
                end = today - timedelta(days=RECENT_DAYS)
                if end >= limit:
                    start = max(limit, end - timedelta(days=HISTORY_SPAN - 1))
                    count += bool(await enqueue_fetch(session, connection, data_type, mode, start, end,
                                                      priority=PRIORITY["history"], reason="onboard",
                                                      walk_back_to=limit))
        await queue.complete(session, ctx.job, {"planned": count})


async def reconcile(ctx: Context) -> None:
    async with fenced(ctx.job) as session:
        connection = await _connection(session, ctx.job)
        count = await plan_recent(session, connection, RECONCILE_DAYS, priority=PRIORITY["reconcile"],
                                  reason=ctx.job.payload.get("reason", "reconcile"), operation_id=ctx.job.operation_id)
        await queue.complete(session, ctx.job, {"planned": count})


async def reverify(ctx: Context) -> None:
    """Đọc lại một lát 7 ngày của lịch sử cũ hơn cho mỗi loại, xoay vòng lùi dần; bắt các lần sửa muộn và khoảng trống."""
    async with fenced(ctx.job) as session:
        connection = await _connection(session, ctx.job)
        today = today_for(connection)
        count = 0
        for data_type in enabled_types(connection.granted_scopes or []):
            for mode in modes(data_type):
                if mode == SERIES:
                    continue  # chuỗi dày chỉ được reconcile đọc lại (chi phí có giới hạn)
                row = (await session.execute(text(
                    "SELECT reverify_through FROM sync_cursors WHERE connection_id = :c AND data_type = :t "
                    "AND source_family = 'all-sources'"), {"c": connection.id, "t": data_type})).first()
                limit = today - timedelta(days=horizon(data_type, mode) - 1)
                end = (row[0] if row and row[0] else today - timedelta(days=RECONCILE_DAYS)) - timedelta(days=1)
                if end < limit:
                    end = today - timedelta(days=RECONCILE_DAYS + 1)  # đã vòng hết: bắt đầu lại từ mép gần đây
                start = max(limit, end - timedelta(days=REVERIFY_SLICE - 1))
                count += bool(await enqueue_fetch(session, connection, data_type, mode, start, end,
                                                  priority=PRIORITY["reverify"], reason="reverify"))
                await session.execute(text(
                    "UPDATE sync_cursors SET reverify_through = :start WHERE connection_id = :c AND data_type = :t "
                    "AND source_family = 'all-sources'"), {"start": start, "c": connection.id, "t": data_type})
        await queue.complete(session, ctx.job, {"planned": count})


def _parse(data_type: str, raw_points: list[dict], *, rollup: bool):
    parser = adapter_for(data_type, set(settings.GH_V4BETA_TYPES))
    parsed = []
    rejected = unknown = 0
    for raw in raw_points:
        point = parser.parse_rollup(data_type, raw, daily=True) if rollup else parser.parse_point(data_type, raw)
        if any(code == BAD_TYPE for code in point.quality.values()):
            rejected += 1
        if point.unknown_paths:
            unknown += 1
        parsed.append((point, raw))
    return parsed, rejected, unknown


async def fetch_window(ctx: Context) -> None:
    job = ctx.job
    data_type, mode = job.data_type, job.payload["mode"]
    start, end = job.window_start, job.window_end
    async with get_db_session() as session:
        connection = await _connection(session, job)
    item = spec(data_type)
    granted = contract_scopes.can_read(item.scope_group, connection.granted_scopes or [])
    if not granted or data_type not in enabled_types(connection.granted_scopes or []):
        status = "NOT_GRANTED" if not granted else "UNSUPPORTED"  # đã được cấp, nhưng hiện HercFit không đọc nó
        async with fenced(job) as session:
            await _cursor(session, connection, data_type, status=status)
            await queue.complete(session, job, {"status": status})
        return
    client = await _client(ctx, connection, data_type)
    if mode == SERIES:
        await _fetch_series(ctx, connection, client)
        return
    progress = dict(job.progress or {})
    progress.setdefault("pages", 0)
    progress.setdefault("points", 0)
    progress.setdefault("rejected", 0)
    progress.setdefault("unknown", 0)
    plan = reads.plan(data_type, rollup=mode == ROLLUP,
                      api_version=api_version_for(data_type, set(settings.GH_V4BETA_TYPES)) or "v4")
    budget = reads.MAX_PAGES
    chunks = list(reads.chunks(start, end + timedelta(days=1), plan.chunk_days)) if mode == ROLLUP else [
        (start, end + timedelta(days=1))]
    chunk_index = int(progress.get("chunk", 0))
    while chunk_index < len(chunks):
        chunk_start, chunk_stop = chunks[chunk_index]
        token = progress.get("page_token")
        if budget == 0:
            async with fenced(job) as session:
                await queue.requeue(session, job, progress)
            return
        page: Page = (await client.daily_rollup_page(data_type, chunk_start, chunk_stop, page_size=plan.page_size,
                                                     page_token=token) if mode == ROLLUP else
                      await client.list_page(data_type, filter=reads.list_filter(plan, start, end + timedelta(days=1)),
                                             page_size=plan.page_size, page_token=token))
        budget -= 1
        parsed, rejected, unknown = _parse(data_type, page.points, rollup=mode == ROLLUP)
        if data_type == "electrocardiogram":  # chỉ lọc được theo cận dưới
            parsed = [(point, raw) for point, raw in parsed if not point.time.civil_date or point.time.civil_date <= end]
        progress.update(pages=progress["pages"] + 1, points=progress["points"] + len(parsed),
                        rejected=progress["rejected"] + rejected, unknown=progress["unknown"] + unknown)
        if page.next_token:
            progress["page_token"] = page.next_token
        else:
            progress.pop("page_token", None)
            chunk_index += 1
            progress["chunk"] = chunk_index
        async with fenced(job) as session:
            await stage.stage(session, connection_id=connection.id, user_id=connection.user_id,
                              generation=connection.generation, root_id=job.root_id or job.id, points=parsed,
                              rollup=mode == ROLLUP, zone=connection.timezone or DEFAULT_TIMEZONE)
            if chunk_index < len(chunks) or page.next_token:
                await queue.save_progress(session, job, progress)
    await _finish_window(ctx, connection, progress)


async def _finish_window(ctx: Context, connection: HealthConnection, progress: dict[str, Any]) -> None:
    job = ctx.job
    data_type, mode = job.data_type, job.payload["mode"]
    start, end = job.window_start, job.window_end
    zone = connection.timezone or DEFAULT_TIMEZONE
    result: dict[str, Any] = {"status": "COMPLETE", **{k: progress[k] for k in ("pages", "points", "rejected", "unknown")}}
    async with fenced(job) as session:
        root = job.root_id or job.id
        if progress["rejected"] == 0:
            result["deleted_remote"] = len(await stage.sweep(session, connection_id=connection.id, data_type=data_type,
                                                             root_id=root, start=start, end=end))
        if settings.GH_INGEST_V2 == "primary":
            outcome = await applying.apply(session, connection_id=connection.id, user_id=connection.user_id,
                                           data_type=data_type, mode=mode, start=start, end=end, zone=zone)
            result["applied"] = outcome["counts"]
            await publish(session, "health.records.changed", connection.user_id,
                          {"data_types": [data_type], "start": start.isoformat(), "end": end.isoformat()})
            from domains.analytics.services import jobs as analytics_jobs
            await analytics_jobs.enqueue(session, connection.user_id)
        elif settings.GH_INGEST_V2 == "shadow":
            await queue.enqueue(session, "SHADOW_COMPARE", queue="maint", connection_id=connection.id,
                                user_id=connection.user_id, data_type=data_type, window_start=start, window_end=end,
                                dedupe_key=f"shadow:{connection.id}:{data_type}:{mode}:{start}:{end}",
                                connection_generation=connection.generation, payload={"mode": mode}, priority=5)
        await _cursor(session, connection, data_type, status="COMPLETE" if progress["rejected"] == 0 else "UNCLEAN",
                      start=start, end=end)
        await _walk_back(session, connection, job)
        await queue.complete(session, job, result)


async def _walk_back(session, connection: HealthConnection, job: Job) -> None:
    limit = job.payload.get("walk_back_to")
    if not limit:
        return
    limit = date.fromisoformat(limit)
    if job.window_start <= limit:
        return
    mode = job.payload["mode"]
    span = 1 if mode == SERIES else HISTORY_SPAN
    end = job.window_start - timedelta(days=1)
    start = max(limit, end - timedelta(days=span - 1))
    await enqueue_fetch(session, connection, job.data_type, mode, start, end, priority=job.priority,
                        walk_back_to=limit, reason=job.payload.get("reason", "history"))


async def _fetch_series(ctx: Context, connection: HealthConnection, client: GoogleHealthClient) -> None:
    """Một ngày UTC của một loại dày: đọc trọn, rồi thay nguyên tử các chunk của ngày đó."""
    job = ctx.job
    data_type, day = job.data_type, job.window_start
    # Dạng filter lấy từ schema của phiên bản thực sự được gọi (các loại chỉ có trên v4beta).
    plan = reads.plan(data_type, rollup=False,
                      api_version=api_version_for(data_type, set(settings.GH_V4BETA_TYPES)) or "v4")
    low, high = series.utc_day(day)
    path = spec(data_type).filter_path
    stamp = lambda moment: moment.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    field = "sample_time.physical_time" if plan.filter_fn == "sample" else "interval.start_time"
    query = f'{path}.{field} >= "{stamp(low)}" AND {path}.{field} < "{stamp(high)}"'
    fetch = await client.list_all(data_type, filter=query, page_size=plan.page_size, max_pages=reads.MAX_PAGES)
    parsed, rejected, unknown = _parse(data_type, fetch.points, rollup=False)
    if not fetch.complete:
        async with fenced(job) as session:
            await _cursor(session, connection, data_type, status="INCOMPLETE", error="series_page_budget")
            await queue.needs_attention(session, job, error_class="SCHEMA", error_code="series_page_budget")
        return
    chunks = series.build(data_type, [(point, stage.source_key(point)) for point, _ in parsed
                                      if point.time.physical_start and low <= point.time.physical_start < high])
    retention = day + timedelta(days=stage.RETENTION_DAYS[spec(data_type).retention])
    async with fenced(job) as session:
        await session.execute(delete(HealthSeriesChunk).where(
            HealthSeriesChunk.user_id == connection.user_id, HealthSeriesChunk.data_type == data_type,
            HealthSeriesChunk.chunk_start >= low, HealthSeriesChunk.chunk_start < high))
        rows = series.rows_for_insert(chunks, user_id=connection.user_id, connection_id=connection.id,
                                      retention_until=retention)
        if rows:
            await session.execute(insert(HealthSeriesChunk.__table__).values(rows))
        await _cursor(session, connection, data_type, status="COMPLETE" if rejected == 0 else "UNCLEAN",
                      start=day, end=day)
        await _walk_back(session, connection, job)
        await queue.complete(session, job, {"status": "COMPLETE", "points": len(parsed), "chunks": len(rows),
                                            "rejected": rejected, "unknown": unknown, "pages": fetch.pages})


async def identity_refresh(ctx: Context) -> None:
    async with get_db_session() as session:
        connection = await _connection(session, ctx.job)
    client = await _client(ctx, connection)
    identity = await client.get_identity()
    devices: list[dict] = []
    if contract_scopes.can_read("settings", connection.granted_scopes or []):
        try:
            devices = await client.list_paired_devices()
        except GoogleHealthError as exc:
            if exc.error_class != PERMISSION:
                raise
    async with fenced(ctx.job) as session:
        connection = await _connection(session, ctx.job)
        if identity.get("healthUserId"):
            connection.health_user_id = str(identity["healthUserId"])[:255]
        for device in devices:
            name = str(device.get("name") or "")[:300]
            if not name:
                continue
            values = {"device_type": device.get("deviceType"), "device_version": device.get("deviceVersion"),
                      "battery_level": device.get("batteryLevel"), "battery_status": device.get("batteryStatus"),
                      "features": device.get("features") or [],
                      "last_sync_at": _timestamp(device.get("lastSyncTime"))}
            statement = insert(PairedDevice.__table__).values(
                id=uuid7(), user_id=connection.user_id, connection_id=connection.id, external_id=name, **values)
            await session.execute(statement.on_conflict_do_update(
                index_elements=["connection_id", "external_id"], set_={**values, "updated_at": datetime.now(timezone.utc)}))
        await queue.complete(session, ctx.job, {"health_user_id": bool(connection.health_user_id),
                                                "devices": len(devices)})


def _timestamp(value: Any) -> datetime | None:
    from integrations.google_health.adapters.base import parse_timestamp
    return parse_timestamp(value)


async def webhook_route(ctx: Context) -> None:
    """Biến các thông báo đã nhận thành các lần fetch gộp; bản trùng và đảo thứ tự đều vô hại."""
    routed = unknown = ignored = 0
    async with fenced(ctx.job) as session:
        rows = (await session.execute(text("""
            SELECT id, health_user_id, data_type, intervals FROM webhook_inbox WHERE state = 'RECEIVED'
            ORDER BY received_at LIMIT 200 FOR UPDATE SKIP LOCKED"""))).all()
        for row in rows:
            connection = (await session.execute(select(HealthConnection).where(
                HealthConnection.health_user_id == row.health_user_id, HealthConnection.status == "ACTIVE",
                HealthConnection.is_active.is_(True)))).scalar_one_or_none()
            data_type = row.data_type
            if connection is None:
                state, unknown = "UNKNOWN_USER", unknown + 1
            elif data_type not in DATA_TYPES or data_type not in enabled_types(connection.granted_scopes or []):
                state, ignored = "IGNORED", ignored + 1
            else:
                days = _days(row.intervals) or [today_for(connection)]
                job_id = None
                for mode in modes(data_type):
                    if mode == SERIES:
                        for day in sorted({d for d in days}):
                            job_id = await enqueue_fetch(session, connection, data_type, mode, day, day,
                                                         priority=PRIORITY["webhook"], reason="webhook") or job_id
                    else:
                        job_id = await enqueue_fetch(session, connection, data_type, mode, min(days), max(days),
                                                     priority=PRIORITY["webhook"], reason="webhook") or job_id
                state, routed = "ROUTED", routed + 1
                await session.execute(text("UPDATE webhook_inbox SET job_id = :job WHERE id = :id"),
                                      {"job": job_id, "id": row.id})
            await session.execute(text("UPDATE webhook_inbox SET state = :state, processed_at = now() WHERE id = :id"),
                                  {"state": state, "id": row.id})
        await queue.complete(session, ctx.job, {"routed": routed, "unknown_user": unknown, "ignored": ignored})


def _days(intervals: Any) -> list[date]:
    """Các ngày địa phương mà một thông báo bao phủ (civilDateTimeInterval, nếu không thì civilIso8601TimeInterval)."""
    days: set[date] = set()
    for interval in intervals or []:
        interval = interval or {}
        bounds: list[date] = []
        civil = interval.get("civilDateTimeInterval") or {}
        for key in ("startDateTime", "endDateTime"):
            value = (civil.get(key) or {}).get("date") or {}
            try:
                bounds.append(date(int(value["year"]), int(value["month"]), int(value["day"])))
            except (KeyError, TypeError, ValueError):
                continue
        if not bounds:
            iso = interval.get("civilIso8601TimeInterval") or {}
            for key in ("startTime", "endTime"):
                try:
                    bounds.append(date.fromisoformat(str(iso.get(key) or "")[:10]))
                except ValueError:
                    continue
        if bounds:
            first, last = min(bounds), max(bounds)
            while first <= last and len(days) < 31:
                days.add(first)
                first += timedelta(days=1)
    return sorted(days)


async def shadow_compare(ctx: Context) -> None:
    job = ctx.job
    async with fenced(job) as session:
        connection = await _connection(session, job)
        diffs = await applying.compare(session, connection_id=connection.id, user_id=connection.user_id,
                                       data_type=job.data_type, mode=job.payload["mode"], start=job.window_start,
                                       end=job.window_end, zone=connection.timezone or DEFAULT_TIMEZONE)
        for diff in diffs[:200]:
            await session.execute(text("""
                INSERT INTO shadow_diffs (id, connection_id, data_type, window_start, window_end, diff_kind, details)
                VALUES (:id, :connection, :data_type, :start, :end, :kind, CAST(:details AS jsonb))"""),
                {"id": uuid7(), "connection": connection.id, "data_type": job.data_type, "start": job.window_start,
                 "end": job.window_end, "kind": diff["kind"], "details": json.dumps(diff, default=str)})
        await queue.complete(session, job, {"diffs": len(diffs)})


async def retention_sweep(ctx: Context) -> None:
    async with fenced(ctx.job) as session:
        counts = {}
        if settings.HEALTH_RETENTION_ENFORCE:
            for table in ("health_series_chunks", "health_source_records"):
                counts[table] = (await session.execute(text(
                    f"DELETE FROM {table} WHERE retention_until IS NOT NULL AND retention_until < CURRENT_DATE"))).rowcount
            counts["ecg_waveforms"] = (await session.execute(text(
                "UPDATE ecg_recordings SET waveform_zlib = NULL WHERE waveform_zlib IS NOT NULL "
                "AND retention_until IS NOT NULL AND retention_until < CURRENT_DATE"))).rowcount
            counts["workout_routes"] = (await session.execute(text(
                "DELETE FROM workout_routes WHERE retention_until IS NOT NULL AND retention_until < CURRENT_DATE"))).rowcount
        await queue.complete(session, ctx.job, counts)


ROUTE_BATCH = 10
ROUTE_RETENTION_DAYS = 90


def can_read_routes(scopes: list[str] | None) -> bool:
    """exportExerciseTcx cần một scope vận động VÀ một scope location."""
    granted = scopes or []
    return contract_scopes.can_read("location", granted) and contract_scopes.can_read("activity_and_fitness", granted)


async def route_fetch(ctx: Context) -> None:
    """GH_ROUTE_FETCH: tải lộ trình GPS (TCX) của các buổi vận động gần đây có lộ trình.

    Lưu dạng nén với thời hạn 90 ngày, chỉ cho người dùng: lộ trình không bao giờ vào
    ngữ cảnh trợ lý, prompt hay knowledge graph. Buổi vận động đã xoá trên Google
    (404) bị bỏ qua; thiếu scope location thì kết thúc job mà không thử lại.
    """
    import hashlib
    import zlib

    from domains.health_records.models.clinical import WorkoutRoute
    from domains.health_records.models.device_records import DeviceWorkout

    async with get_db_session() as session:
        connection = await _connection(session, ctx.job)
        if not can_read_routes(connection.granted_scopes):
            await queue.complete(session, ctx.job, {"skipped": "location_not_granted"})
            return
        since = datetime.now(timezone.utc) - timedelta(days=ROUTE_RETENTION_DAYS)
        workouts = (await session.execute(select(DeviceWorkout.id, DeviceWorkout.external_id).where(
            DeviceWorkout.user_id == connection.user_id, DeviceWorkout.is_active.is_(True),
            DeviceWorkout.has_route.is_(True), DeviceWorkout.started_at >= since,
            DeviceWorkout.external_id.like("users/%/dataTypes/exercise/dataPoints/%"),
            ~select(WorkoutRoute.workout_id).where(WorkoutRoute.workout_id == DeviceWorkout.id).exists(),
        ).order_by(DeviceWorkout.started_at.desc()).limit(ROUTE_BATCH))).all()
    client = await _client(ctx, connection, "exercise")
    fetched, gone = [], 0
    for workout_id, name in workouts:
        try:
            fetched.append((workout_id, await client.export_exercise_tcx(name)))
        except GoogleHealthError as exc:
            if exc.status == 404:
                gone += 1
                continue
            if exc.error_class == PERMISSION:
                break
            raise
    today = datetime.now(timezone.utc).date()
    async with fenced(ctx.job) as session:
        for workout_id, data in fetched:
            values = {"data_zlib": zlib.compress(data, 6), "sha256": hashlib.sha256(data).hexdigest(), "partial": False,
                      "fetched_at": datetime.now(timezone.utc),
                      "retention_until": today + timedelta(days=ROUTE_RETENTION_DAYS)}
            statement = insert(WorkoutRoute.__table__).values(workout_id=workout_id, user_id=connection.user_id,
                                                              format="TCX", **values)
            await session.execute(statement.on_conflict_do_update(index_elements=["workout_id"], set_=values))
        await queue.complete(session, ctx.job, {"routes": len(fetched), "gone": gone, "candidates": len(workouts)})


async def legacy_sync(ctx: Context) -> None:
    """GH_INGEST_V2=off với worker riêng: sync trong tiến trình, do worker chạy thay cho API."""
    from integrations.google_health.scheduler import sync_due
    synced = await sync_due()
    async with get_db_session() as session:
        await queue.complete(session, ctx.job, {"synced": synced})


HANDLERS = {
    "GH_ONBOARD": onboard, "GH_FETCH_WINDOW": fetch_window, "GH_RECONCILE": reconcile, "GH_REVERIFY": reverify,
    "GH_WEBHOOK_ROUTE": webhook_route, "GH_IDENTITY_REFRESH": identity_refresh, "SHADOW_COMPARE": shadow_compare,
    "RETENTION_SWEEP": retention_sweep, "GH_LEGACY_SYNC": legacy_sync, "GH_ROUTE_FETCH": route_fetch,
}
