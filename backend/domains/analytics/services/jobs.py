"""ANALYTICS_RECOMPUTE: làm mới độ phủ (30 ngày) và đường nền 28 ngày cho một người dùng sau khi có dữ liệu mới."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.database import get_db_session
from core.jobs import queue
from domains.analytics.services import context_api, coverage


async def recompute(ctx) -> None:
    job = ctx.job
    today = datetime.now(timezone.utc).date()
    async with get_db_session() as session:
        await queue.fence(session, job)
        report = await coverage.coverage(session, job.user_id, today - timedelta(days=29), today)
        written = await coverage.store_coverage(session, job.user_id, report)
        await coverage.store_baselines(session, job.user_id, await coverage.baselines(session, job.user_id, today))
        purged = await context_api.purge_snapshots(session, job.user_id)
        await queue.complete(session, job, {"coverage_rows": written, "snapshots_purged": purged})


async def enqueue(session, user_id, *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    await queue.enqueue(session, "ANALYTICS_RECOMPUTE", queue="maint", user_id=user_id, priority=30,
                        dedupe_key=f"analytics:{user_id}:{now:%Y%m%d%H}{now.minute // 10}")


HANDLERS = {"ANALYTICS_RECOMPUTE": recompute}
