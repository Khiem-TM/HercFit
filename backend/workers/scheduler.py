"""Lập kế hoạch định kỳ, mỗi lúc một scheduler (advisory lock cấp transaction cho mỗi tick).

Mỗi tick: trả các lease hết hạn về hàng đợi, định tuyến thông báo webhook, và
với mỗi kết nối đang hoạt động thì xếp hàng onboarding, reconcile mỗi 6 giờ, một lát reverify
hằng ngày và làm mới định danh. Dedupe key mang theo khung thời gian, và việc định kỳ
được lập một lần mỗi khung (`_plan_once`): cả tick chạy hai lần lẫn
các tick sau khi job đã xong đều không lặp lại nó.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from sqlalchemy import select, text

from core.database import get_db_session
from core.jobs import queue
from core.settings import settings
from integrations.google_health.ingest.jobs import can_read_routes
from integrations.google_health.models import HealthConnection

logger = logging.getLogger(__name__)
TICK_SECONDS = 60
LOCK = "hercfit-scheduler"


def _bucket(hours: int, now: datetime) -> str:
    return f"{now:%Y%m%d}-{now.hour // hours}"


async def _plan_once(session, kind: str, *, dedupe_key: str, **values) -> bool:
    """Lập việc định kỳ một lần cho mỗi khung thời gian (được khoá đặt tên), bất kể kết quả của nó.

    Dedupe của chính hàng đợi chỉ bao quát job đang chờ, nên khi chưa có kiểm tra này, một job theo ngày
    xong trong một phút đã bị lập lại ở mọi tick (ix_jobs_kind_dedupe).
    """
    seen = (await session.execute(text("SELECT 1 FROM jobs WHERE kind = :kind AND dedupe_key = :key LIMIT 1"),
                                  {"kind": kind, "key": dedupe_key})).first()
    return not seen and bool(await queue.enqueue(session, kind, dedupe_key=dedupe_key, **values))


async def tick(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    planned = {"reaped": 0, "jobs": 0}
    async with get_db_session() as session:
        locked = (await session.execute(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
                                        {"k": LOCK})).scalar_one()
        if not locked:
            return planned
        planned["reaped"] = await queue.reap(session)
        if settings.GH_EXPORT_DISPATCH:
            rows = (await session.execute(text("""
                SELECT DISTINCT o.connection_id, c.user_id, c.generation FROM export_outbox o
                JOIN health_connections c ON c.id = o.connection_id AND c.status = 'ACTIVE'
                WHERE o.state IN ('PENDING', 'VERIFYING') AND o.available_at <= now()"""))).all()
            for row in rows:
                planned["jobs"] += bool(await queue.enqueue(
                    session, "GH_EXPORT_DISPATCH", queue="export", connection_id=row.connection_id,
                    user_id=row.user_id, connection_generation=row.generation, priority=60,
                    dedupe_key=f"export:{row.connection_id}"))
        if settings.GH_INGEST_V2 == "off":
            if settings.GH_WORKER_EXTERNAL:
                planned["jobs"] += bool(await queue.enqueue(session, "GH_LEGACY_SYNC", queue="ingest",
                                                            dedupe_key=f"legacy:{now:%Y%m%d%H%M}", priority=60))
            return planned
        pending = (await session.execute(text(
            "SELECT 1 FROM webhook_inbox WHERE state = 'RECEIVED' LIMIT 1"))).first()
        if pending:
            planned["jobs"] += bool(await queue.enqueue(session, "GH_WEBHOOK_ROUTE", dedupe_key="webhook-route",
                                                        priority=95))
        planned["jobs"] += await _plan_once(session, "RETENTION_SWEEP", queue="maint",
                                            dedupe_key=f"retention:{now:%Y%m%d}", priority=1)
        connections = (await session.execute(select(HealthConnection).where(
            HealthConnection.status == "ACTIVE", HealthConnection.is_active.is_(True)))).scalars().all()
        for connection in connections:
            base = {"user_id": connection.user_id, "connection_id": connection.id,
                    "connection_generation": connection.generation}
            onboarded = (await session.execute(text(
                "SELECT 1 FROM sync_cursors WHERE connection_id = :c LIMIT 1"), {"c": connection.id})).first()
            if not onboarded:
                planned["jobs"] += bool(await queue.enqueue(
                    session, "GH_ONBOARD", dedupe_key=f"onboard:{connection.id}:{connection.generation}",
                    priority=85, **base))
            planned["jobs"] += await _plan_once(
                session, "GH_RECONCILE", dedupe_key=f"reconcile:{connection.id}:{_bucket(6, now)}", priority=70,
                **base)
            planned["jobs"] += await _plan_once(
                session, "GH_REVERIFY", queue="maint", dedupe_key=f"reverify:{connection.id}:{now:%Y%m%d}",
                priority=10, **base)
            if can_read_routes(connection.granted_scopes):
                planned["jobs"] += await _plan_once(
                    session, "GH_ROUTE_FETCH", queue="maint", dedupe_key=f"routes:{connection.id}:{now:%Y%m%d}",
                    priority=15, **base)
            if not connection.health_user_id:
                # Một lời gọi rẻ, và webhook không định tuyến được nếu thiếu nó: xếp trước các lần fetch onboarding
                # (cùng độ ưu tiên như sau OAuth callback).
                planned["jobs"] += await _plan_once(
                    session, "GH_IDENTITY_REFRESH", dedupe_key=f"identity:{connection.id}:{now:%Y%m%d}",
                    priority=95, **base)
    return planned


async def loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 - tick sau sẽ thử lại
            logger.warning("scheduler_tick_failed error=%s", type(exc).__name__)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
