"""Hộp thư thông báo: tuỳ chọn của người dùng, đánh giá → soạn → gửi (có dedup, giới hạn, giờ yên lặng)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError

from domains.analytics.services.daily_health import service as daily_health
from domains.health_records import ports
from domains.identity import consent
from domains.identity.models.user import User
from domains.notifications.models.notification import UserNotification
from domains.notifications.schemas.notification import (
    NotificationList,
    NotificationPreferences,
    NotificationPreferencesRead,
    NotificationRead,
)
from domains.notifications.services import briefing


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def preferences(session, user) -> NotificationPreferencesRead:
    stored = (user.personal_info or {}).get("notifications") or {}
    try:
        prefs = NotificationPreferences.model_validate({key: value for key, value in stored.items() if key != "enabled"})
    except ValidationError:
        prefs = NotificationPreferences()  # dữ liệu cũ hỏng không làm hỏng thông báo: quay về mặc định
    return NotificationPreferencesRead(**prefs.model_dump(exclude={"enabled"}),
                                       enabled=await consent.proactive_enabled(session, user.id),
                                       timezone=await ports.user_timezone(session, user.id))


async def save_preferences(session, user, update: NotificationPreferences) -> NotificationPreferencesRead:
    await consent.set_proactive(session, user.id, update.enabled)
    saved = await User.update_personal_info(session, user.id, {"notifications": update.model_dump(exclude={"enabled"})})
    return await preferences(session, saved or user)


async def deliver(session, user_id: UUID, drafts: list[briefing.Draft], prefs: NotificationPreferences,
                  local_now: datetime, *, force: bool = False) -> list[UUID]:
    """Lưu các bản nháp chưa từng gửi, theo ưu tiên, trong giới hạn mỗi ngày; im lặng trong giờ yên lặng."""
    if not drafts or (not force and briefing.quiet(prefs, local_now)):
        return []
    known = await UserNotification.keys(session, user_id, [draft.dedup_key for draft in drafts])
    used = await UserNotification.count_for_day(session, user_id, local_now.date())
    created = []
    for draft in drafts:
        if draft.dedup_key in known:
            continue
        if used >= prefs.max_per_day and not force:
            break
        midnight = datetime.combine(local_now.date(), datetime.min.time(), local_now.tzinfo)
        notification_id = await UserNotification.insert_unique(session, {
            "user_id": user_id, "kind": draft.kind, "code": draft.code, "priority": draft.priority,
            "local_date": local_now.date(), "dedup_key": draft.dedup_key, "title": draft.title, "body": draft.body,
            "payload": draft.payload, "expires_at": midnight + timedelta(days=draft.ttl_days)})
        if notification_id is not None:
            created.append(notification_id)
            used += 1
    return created


async def evaluate(session, user, *, now: datetime | None = None, force: bool = False) -> list[UUID]:
    """Đánh giá hôm nay của người dùng và gửi những thông báo đến hạn; không làm gì khi chưa bật proactive."""
    if not await consent.proactive_enabled(session, user.id):
        return []
    now = now or _now()
    prefs = await preferences(session, user)
    local_now = now.astimezone(ZoneInfo(prefs.timezone))
    assessment = await daily_health.assess(session, user, zone=prefs.timezone, now=now)
    drafts = briefing.compose(assessment, prefs, local_now, force=force)
    return await deliver(session, user.id, drafts, prefs, local_now, force=force)


async def inbox(session, user_id: UUID, *, unread_only: bool = False, limit: int = 20) -> NotificationList:
    now = _now()
    items = await UserNotification.list_for(session, user_id, now=now, unread_only=unread_only, limit=limit)
    return NotificationList(items=[NotificationRead.model_validate(item) for item in items],
                            unread=await UserNotification.unread_count(session, user_id, now=now))


async def _owned(session, user_id: UUID, notification_id: UUID) -> UserNotification:
    found = await UserNotification.owned(session, user_id, notification_id)
    if found is None:
        raise HTTPException(404, "Không tìm thấy thông báo")
    return found


async def mark_seen(session, user_id: UUID, notification_id: UUID) -> NotificationRead:
    found = await _owned(session, user_id, notification_id)
    found.seen_at = found.seen_at or _now()
    await session.flush()
    return NotificationRead.model_validate(found)


async def dismiss(session, user_id: UUID, notification_id: UUID) -> None:
    found = await _owned(session, user_id, notification_id)
    found.dismissed_at = found.dismissed_at or _now()
    found.seen_at = found.seen_at or found.dismissed_at
    await session.flush()
