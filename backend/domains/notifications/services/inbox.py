"""Hộp thư thông báo: tuỳ chọn, luật → soạn → gửi (dedup, thời gian chờ, giới hạn mỗi ngày, giờ yên lặng).

Mỗi lần xét (vòng lặp gọi mỗi nhịp, hoặc người dùng bấm "Tạo đánh giá hôm nay"):
1. nhắc lịch tập (buổi hôm nay, buổi bị lỡ) và đề xuất điều chỉnh khi điểm sẵn sàng thấp;
2. cảnh báo chỉ số: bộ luật (health_rules) → bỏ những gì đã báo hoặc đang trong thời gian chờ → chỉ khi đó
   mới gọi LLM viết lời (composer), để không tốn lượt gọi ở mỗi nhịp;
3. đánh giá ngày: từ giờ người dùng chọn, một lần mỗi ngày (dedup_key review:<ngày>).
Gửi xong, mỗi thông báo mới được phát qua WebSocket (realtime.publish, giao khi transaction commit).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from domains.analytics.services import day_review
from domains.analytics.services.daily_health import service as daily_health
from domains.analytics.services.health_rules import catalog, features as rule_features
from domains.analytics.services.health_rules.evaluate import Signal, evaluate as evaluate_rules
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
from domains.notifications.services import composer, realtime, reminders
from domains.notifications.services.drafts import Draft, clock, quiet

STORED_FIELDS = frozenset(NotificationPreferences.model_fields) - {"enabled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def preferences(session, user) -> NotificationPreferencesRead:
    stored = (user.personal_info or {}).get("notifications") or {}
    # Bỏ khoá của phiên bản tuỳ chọn cũ (briefing_time, categories...) thay vì mất mọi cài đặt còn lại.
    known = {key: value for key, value in stored.items() if key in STORED_FIELDS}
    try:
        prefs = NotificationPreferences.model_validate(known)
    except ValueError:
        prefs = NotificationPreferences()  # dữ liệu cũ hỏng không làm hỏng thông báo: quay về mặc định
    return NotificationPreferencesRead(**prefs.model_dump(exclude={"enabled"}),
                                       enabled=await consent.proactive_enabled(session, user.id),
                                       timezone=await ports.user_timezone(session, user.id))


async def save_preferences(session, user, update: NotificationPreferences) -> NotificationPreferencesRead:
    await consent.set_proactive(session, user.id, update.enabled)
    saved = await User.update_personal_info(session, user.id, {"notifications": update.model_dump(exclude={"enabled"})})
    return await preferences(session, saved or user)


async def deliver(session, user_id: UUID, drafts: list[Draft], prefs: NotificationPreferences,
                  local_now: datetime, *, force: bool = False) -> list[UUID]:
    """Lưu các bản nháp chưa từng gửi, theo ưu tiên, trong giới hạn mỗi ngày; im lặng trong giờ yên lặng.

    Cảnh báo khẩn không tính vào giới hạn mỗi ngày, nhưng vẫn chờ hết giờ yên lặng."""
    if not drafts or (not force and quiet(prefs, local_now)):
        return []
    known = await UserNotification.keys(session, user_id, [draft.dedup_key for draft in drafts])
    used = await UserNotification.count_for_day(session, user_id, local_now.date())
    created = []
    midnight = datetime.combine(local_now.date(), datetime.min.time(), local_now.tzinfo)
    for draft in sorted(drafts, key=lambda item: (not item.urgent, item.priority)):
        if draft.dedup_key in known:
            continue
        if used >= prefs.max_per_day and not (force or draft.urgent):
            continue
        notification_id = await UserNotification.insert_unique(session, {
            "user_id": user_id, "kind": draft.kind, "code": draft.code, "priority": draft.priority,
            "local_date": local_now.date(), "dedup_key": draft.dedup_key, "title": draft.title, "body": draft.body,
            "payload": draft.payload, "expires_at": midnight + timedelta(days=draft.ttl_days)})
        if notification_id is not None:
            created.append(notification_id)
            await realtime.publish(session, user_id, "created", notification_id)
            if not draft.urgent:
                used += 1
    return created


async def _move_missed(session, user_id: UUID, plan, context: reminders.Context, local_now: datetime):
    """Tuỳ chọn "auto": dời từng buổi bị lỡ (chưa báo lần nào) sang ngày trống gần nhất; trả về lịch hiện hành."""
    for missed in list(context.missed):
        if await UserNotification.keys(session, user_id, [f"missed:{missed.entry_id}"]):
            continue
        target = reminders.free_day(plan, local_now.date())
        moved = target and await reminders.move_missed(session, user_id, plan, missed.entry_id, target)
        if moved:
            plan = moved
            context.moved.append((missed, target))
    context.missed = []
    return plan


def alert_code(signal: Signal) -> str:
    return f"ALERT_{signal.rule.upper()}"


async def fresh_signals(session, user_id: UUID, signals: list[Signal], today) -> list[Signal]:
    """Bỏ tín hiệu đã gửi (cùng dedup_key) hoặc còn trong thời gian chờ của luật (trừ khi mức độ tăng lên)."""
    if not signals:
        return []
    longest = max(signal.meta.cooldown_days for signal in signals)
    history = await UserNotification.recent(session, user_id, [alert_code(signal) for signal in signals],
                                            today - timedelta(days=longest))
    keys = await UserNotification.keys(session, user_id, [
        f"alert:{signal.rule}:{signal.severity}:{signal.anchor.isoformat()}" for signal in signals])
    kept = []
    for signal in signals:
        if f"alert:{signal.rule}:{signal.severity}:{signal.anchor.isoformat()}" in keys:
            continue
        rank, since = catalog.SEVERITY_RANK[signal.severity], today - timedelta(days=signal.meta.cooldown_days)
        if any(code == alert_code(signal) and day > since and sent >= rank for code, day, sent in history):
            continue
        kept.append(signal)
    return kept


async def review_due(session, user_id: UUID, prefs: NotificationPreferences, local_now: datetime) -> bool:
    if not prefs.daily_review or local_now.time() < clock(prefs.daily_review_time):
        return False
    return not await UserNotification.keys(session, user_id, [f"review:{local_now.date().isoformat()}"])


async def evaluate(session, user, *, now: datetime | None = None, force: bool = False,
                   health: bool = True) -> list[UUID]:
    """Gửi những thông báo đến hạn của người dùng; không làm gì khi chưa bật thông báo chủ động.

    health=False: bỏ qua cảnh báo chỉ số ở nhịp này (vòng lặp chỉ xét chúng khi có dữ liệu mới hoặc mỗi giờ).
    force: người dùng bấm "Tạo đánh giá hôm nay": viết đánh giá ngay, không chờ giờ, giờ yên lặng hay giới hạn."""
    if not await consent.proactive_enabled(session, user.id):
        return []
    now = now or _now()
    prefs = await preferences(session, user)
    local_now = now.astimezone(ZoneInfo(prefs.timezone))
    if quiet(prefs, local_now) and not force:
        return []  # không soạn gì (và không gọi LLM) khi chưa được phép gửi
    today = local_now.date()
    plan = await reminders.current_plan(session, user.id)
    context = await reminders.gather(session, user.id, local_now, plan)
    if plan is not None and prefs.missed_session == "auto" and context.missed:
        plan = await _move_missed(session, user.id, plan, context, local_now)
    drafts = reminders.compose(context, prefs, local_now)

    wants_review = force or await review_due(session, user.id, prefs, local_now)
    alerts = health and prefs.health_alerts and bool(prefs.alert_groups)
    if not (health or wants_review):
        return await deliver(session, user.id, drafts, prefs, local_now, force=force)

    assessment = await daily_health.assess(session, user, zone=prefs.timezone, now=now)
    drafts += reminders.adjust(assessment, context, prefs)
    if not (alerts or wants_review):
        return await deliver(session, user.id, drafts, prefs, local_now, force=force)
    found, profile = await rule_features.gather(session, user, today, prefs.timezone)
    if alerts:
        signals = await fresh_signals(session, user.id, evaluate_rules(found, profile, prefs.alert_groups), today)
        budget = max(0, prefs.max_per_day - await UserNotification.count_for_day(session, user.id, today))
        for signal in signals:
            if signal.severity != "urgent":
                if budget <= 0:
                    continue
                budget -= 1
            drafts.append(await composer.alert(session, user.id, signal, profile))
    if wants_review:
        sessions = [(item.label, False) for item in context.today] + [(item.label, True) for item in context.done_today]
        scored = day_review.review(found, profile, readiness_score=getattr(assessment, "score", None),
                                   sessions=sessions)
        titles = await UserNotification.titles(session, user.id, "alert", today)
        titles += [draft.title for draft in drafts if draft.kind == "alert"]
        drafts.append(await composer.review(session, user.id, scored, profile, alerts=titles,
                                            tomorrow=[item.label for item in context.tomorrow]))
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
    if found.seen_at is None:
        found.seen_at = _now()
        await session.flush()
        await realtime.publish(session, user_id, "seen", notification_id)
    return NotificationRead.model_validate(found)


async def dismiss(session, user_id: UUID, notification_id: UUID) -> None:
    found = await _owned(session, user_id, notification_id)
    if found.dismissed_at is None:
        found.dismissed_at = _now()
        found.seen_at = found.seen_at or found.dismissed_at
        await session.flush()
        await realtime.publish(session, user_id, "dismissed", notification_id)
