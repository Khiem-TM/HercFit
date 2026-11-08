"""Lập lịch briefing: mỗi nhịp tiêu thụ sự kiện `health.synced` và quét người dùng đã tới giờ briefing.

Chạy trong lifespan của API (như vòng đồng bộ Google Health). Nhiều tiến trình cùng chạy vẫn an toàn:
khoá advisory cho phần tiêu thụ sự kiện, và dedup_key duy nhất cho phần tạo thông báo.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from core.database import get_db_session
from core.settings import settings
from domains.health_records import ports
from domains.identity.models.user import User
from domains.notifications.models.notification import UserNotification
from domains.notifications.services import briefing, inbox
from domains.shared import events

logger = logging.getLogger(__name__)
CONSUMER = "backend.daily_briefing"
# Đồng bộ cũ hơn chừng này lúc tới giờ briefing thì đồng bộ ngay để có giấc ngủ đêm qua.
REFRESH_IF_OLDER = timedelta(hours=2)


async def _proactive_users(session) -> list:
    rows = await session.execute(text(
        "SELECT c.user_id FROM user_consents c JOIN users u ON u.id = c.user_id "
        "WHERE c.purpose = 'proactive' AND c.data_group = 'device' AND c.granted AND u.is_active"))
    return [user_id for (user_id,) in rows]


async def run_once(now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    async with get_db_session() as session:
        if not (await session.execute(text(
                "SELECT pg_try_advisory_xact_lock(hashtextextended('daily-briefing', 0))"))).scalar():
            return {"events": 0, "users": 0, "created": 0, "skipped": 1}
        rows = await events.pending(session, CONSUMER, ("health.synced",))
        for row in rows:
            await events.delivered(session, CONSUMER, row["id"])
        synced = {row["user_id"] for row in rows}
        users = await _proactive_users(session)
    created = 0
    for user_id in users:
        try:
            refresh = False
            async with get_db_session() as session:
                user = await session.get(User, user_id)
                prefs = await inbox.preferences(session, user)
                local_now = now.astimezone(ZoneInfo(prefs.timezone))
                due = briefing.briefing_due(prefs, local_now) and not await UserNotification.keys(
                    session, user_id, [f"briefing:{local_now.date().isoformat()}"])
                if user_id not in synced and not due:
                    continue
                if due and user_id not in synced:
                    status = await ports.provider_status(session, user_id)
                    refresh = bool(status is not None and status.connected and (
                        status.last_success_at is None or now - status.last_success_at > REFRESH_IF_OLDER))
            if refresh:
                await ports.refresh(user_id)
            async with get_db_session() as session:
                created += len(await inbox.evaluate(session, await session.get(User, user_id), now=now))
        except Exception as exc:  # một người dùng lỗi không chặn người khác
            logger.warning("daily_briefing_error user=%s error=%s", user_id, type(exc).__name__)
    return {"events": len(rows), "users": len(users), "created": created}


async def daily_briefing_loop() -> None:
    while True:
        try:
            await run_once()
        except Exception as exc:
            logger.warning("daily_briefing_loop_error error=%s", type(exc).__name__)
        await asyncio.sleep(settings.DAILY_BRIEFING_POLL_MINUTES * 60)
