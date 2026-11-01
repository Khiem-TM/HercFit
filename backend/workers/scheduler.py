"""Periodic planning, one scheduler at a time (transaction-level advisory lock per tick).

Every tick: return expired leases to the queue, route webhook notifications, and
per active connection enqueue onboarding, a 6-hourly reconcile, a daily reverify
slice and an identity refresh. Dedupe keys carry the time bucket, and periodic work
is planned once per bucket (`_plan_once`): neither a tick that runs twice nor the
ticks after the job finished can repeat it.
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
    """Plan periodic work once per time bucket (named by the key), whatever became of it.

    The queue's own dedupe covers pending jobs only, so without this check a daily job
    that finished in a minute was planned again on every tick (ix_jobs_kind_dedupe).
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
                # One cheap call, and webhooks cannot be routed without it: ahead of onboarding fetches
                # (same priority as after the OAuth callback).
                planned["jobs"] += await _plan_once(
                    session, "GH_IDENTITY_REFRESH", dedupe_key=f"identity:{connection.id}:{now:%Y%m%d}",
                    priority=95, **base)
    return planned


async def loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await tick()
        except Exception as exc:  # noqa: BLE001 - the next tick retries
            logger.warning("scheduler_tick_failed error=%s", type(exc).__name__)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), TICK_SECONDS)
