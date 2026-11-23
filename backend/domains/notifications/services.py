"""Service nghiệp vụ của miền thông báo."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

from core import service_auth
from core.database import get_db_session, get_postgres_connection_string
from core.settings import settings
from domains.analytics import daily_health, health_rules
from domains.analytics import services as analytics_services
from domains.analytics.health_rules import Profile, Signal, ddmm
from domains.analytics.health_rules import evaluate as evaluate_rules
from domains.analytics.services import DayReview
from domains.health_records import ports
from domains.identity import consent
from domains.identity.models import User
from domains.notifications.models import UserNotification
from domains.notifications.schemas import (
    NotificationList,
    NotificationPreferences,
    NotificationPreferencesRead,
    NotificationRead,
)
from domains.shared import events

# --------------------------------------------------------------------------------------------------
# Viết lời cho cảnh báo chỉ số và đánh giá ngày: LLM (service agentic, qua tool calling) hoặc câu chữ do code.
#
# Backend không phụ thuộc nhà cung cấp model: nó gửi feature và nhãn đã tính sang agentic
# (POST /internal/notifications/compose, ký HMAC như core/service_auth) và nhận lại lời đã viết. Dữ liệu thiết bị
# chỉ rời backend khi người dùng đã cho trợ lý dùng nó (consent "assistant"/"device"). Không có consent,
# agentic chưa cấu hình, lỗi, quá thời gian hay trả về sai dạng: dùng câu chữ do code viết, nên thông báo
# luôn được gửi. Mức độ, ngưỡng và dòng lưu ý y tế luôn do code quyết định, không phải LLM.
# --------------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)
COMPOSE_PATH = "/internal/notifications/compose"
PRIORITY = {"urgent": 1, "warn": 1, "info": 3}


class AlertText(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    body: str = Field(min_length=10, max_length=420)
    advice: list[str] = Field(default_factory=list, max_length=2)
    ask: str = Field(min_length=5, max_length=240)


class ReviewText(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    summary: str = Field(min_length=10, max_length=520)
    highlights: list[str] = Field(default_factory=list, max_length=3)
    improvements: list[str] = Field(default_factory=list, max_length=2)
    tomorrow_tip: str = Field(min_length=5, max_length=240)
    ask: str = Field(min_length=5, max_length=240)


class Composed(BaseModel):
    text: dict[str, Any]
    model: str | None = None
    prompt_version: str | None = None


def profile_summary(profile: Profile) -> dict[str, Any]:
    """Thể trạng ở mức đủ để chọn giọng văn; không gửi họ tên, email hay ngày sinh."""
    return {"sex": profile.sex, "age": profile.age, "goal": profile.goal, "trained": profile.trained}


async def _llm(session, user_id: UUID, kind: str, data: dict[str, Any]) -> Composed | None:
    secret = settings.AGENT_SERVICE_SECRET.get_secret_value() if settings.AGENT_SERVICE_SECRET else ""
    if not settings.AGENTIC_INTERNAL_URL or not secret:
        return None
    if not (await consent.load(session, user_id)).allows("device"):
        return None
    body = json.dumps({"kind": kind, "locale": "vi", "data": data}, ensure_ascii=False, default=str).encode()
    headers = {"Content-Type": "application/json", "X-HercFit-User": str(user_id),
               service_auth.HEADER: service_auth.sign(secret, "POST", COMPOSE_PATH, str(user_id), body)}
    try:
        async with httpx.AsyncClient(base_url=settings.AGENTIC_INTERNAL_URL,
                                     timeout=settings.NOTIFICATION_COMPOSE_TIMEOUT_SECONDS) as client:
            response = await client.post(COMPOSE_PATH, content=body, headers=headers)
        response.raise_for_status()
        return Composed.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        logger.warning("notification_compose_fallback kind=%s error=%s", kind, type(exc).__name__)
        return None


def _notes(severity: str) -> list[str]:
    if severity == "urgent":
        return [health_rules.URGENT_NOTE, health_rules.DISCLAIMER]
    return [health_rules.DISCLAIMER] if severity == "warn" else []


def _alert_ask(signal: Signal) -> str:
    return f"Giải thích giúp mình cảnh báo «{signal.title}» và mình nên làm gì tiếp theo."


async def alert(session, user_id: UUID, signal: Signal, profile: Profile) -> Draft:
    features = signal.features()
    composed = await _llm(session, user_id, "alert", {"profile": profile_summary(profile), "signal": features})
    text = None
    if composed is not None:
        try:
            text = AlertText.model_validate(composed.text)
        except ValidationError:
            text = None
    by = "llm" if text is not None else "template"
    text = text or AlertText(title=signal.title, body=signal.fact, advice=[signal.advice], ask=_alert_ask(signal))
    body = " ".join([text.body, *_notes(signal.severity)])
    payload = {
        "severity": signal.severity, "severity_rank": health_rules.SEVERITY_RANK[signal.severity],
        "group": signal.meta.group, "rule": signal.rule, "features": features, "advice": text.advice, "ask": text.ask,
        "composer": {"by": by, "model": composed.model if by == "llm" else None,
                     "prompt_version": composed.prompt_version if by == "llm" else None},
    }
    return Draft("alert", f"ALERT_{signal.rule.upper()}", PRIORITY[signal.severity],
                 f"alert:{signal.rule}:{signal.severity}:{signal.anchor.isoformat()}", text.title, body, payload,
                 ttl_days=3, urgent=signal.severity == "urgent")


def _review_template(review: DayReview, tomorrow: list[str]) -> ReviewText:
    day = ddmm(review.date)
    if not review.enough:
        return ReviewText(
            title=f"Chưa đủ dữ liệu để đánh giá ngày {day}",
            summary="Hôm nay HercFit chưa có đủ dữ liệu (cần ít nhất hai trong các mặt dinh dưỡng, vận động, giấc ngủ, "
                    "hồi phục, lịch tập) để chấm điểm ngày.",
            tomorrow_tip="Ngày mai ghi bữa ăn và đeo thiết bị khi ngủ để có bản đánh giá đầy đủ.",
            ask="Mình nên ghi những dữ liệu nào để HercFit đánh giá được một ngày?")
    from domains.analytics.services import TIPS

    scored = [d for d in review.dimensions if d.score is not None]
    weakest = review.weakest()
    tip = TIPS[weakest.id] if weakest is not None and weakest.score is not None and weakest.score < 80 else \
        "Giữ nhịp như hôm nay."
    if tomorrow:
        tip += f" Ngày mai bạn có buổi {', '.join(tomorrow)}."
    return ReviewText(
        title=f"Đánh giá ngày {day}: {review.grade} · {review.score}/100",
        summary=" ".join(f"{d.as_dict()['label']}: {d.detail}" for d in scored),
        highlights=[f"{d.as_dict()['label']}: {d.detail}" for d in scored if d.rating == "good"][:3],
        improvements=[f"{d.as_dict()['label']}: {d.detail}" for d in scored if d.rating == "poor"][:2],
        tomorrow_tip=tip, ask="Nhận xét chi tiết hơn về ngày hôm nay của mình và gợi ý cho ngày mai.")


async def review(session, user_id: UUID, day_review: DayReview, profile: Profile, *, alerts: list[str],
                 tomorrow: list[str]) -> Draft:
    data = {"profile": profile_summary(profile), "review": day_review.as_dict(), "alerts_today": alerts,
            "tomorrow_sessions": tomorrow}
    composed = await _llm(session, user_id, "review", data) if day_review.enough else None
    text = None
    if composed is not None:
        try:
            text = ReviewText.model_validate(composed.text)
        except ValidationError:
            text = None
    by = "llm" if text is not None else "template"
    text = text or _review_template(day_review, tomorrow)
    payload = {
        "review": day_review.as_dict(), "highlights": text.highlights, "improvements": text.improvements,
        "tomorrow_tip": text.tomorrow_tip, "ask": text.ask, "alerts": alerts,
        "composer": {"by": by, "model": composed.model if by == "llm" else None,
                     "prompt_version": composed.prompt_version if by == "llm" else None},
    }
    return Draft("review", "DAY_REVIEW", 2, f"review:{day_review.date.isoformat()}", text.title, text.summary,
                 payload, ttl_days=2)


# --------------------------------------------------------------------------------------------------
# Bản nháp thông báo và tiện ích giờ địa phương dùng chung cho cảnh báo, đánh giá ngày và nhắc lịch tập.
#
# dedup_key quyết định "đã báo chưa", nên gọi lại bao nhiêu lần cũng không lặp.
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Draft:
    kind: str
    code: str
    priority: int
    dedup_key: str
    title: str
    body: str
    payload: dict[str, Any] = field(default_factory=dict)
    # Hết hạn sau chừng này ngày kể từ ngày của thông báo.
    ttl_days: int = 2
    # Cảnh báo khẩn: không tính vào giới hạn mỗi ngày (vẫn chờ hết giờ yên lặng).
    urgent: bool = False


def clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def quiet(prefs: NotificationPreferences, local_now: datetime) -> bool:
    if not prefs.quiet_hours.enabled:
        return False
    start, end, now = clock(prefs.quiet_hours.start), clock(prefs.quiet_hours.end), local_now.time()
    if start == end:
        return False
    return start <= now < end if start < end else (now >= start or now < end)


# --------------------------------------------------------------------------------------------------
# Hộp thư thông báo: tuỳ chọn, luật → soạn → gửi (dedup, thời gian chờ, giới hạn mỗi ngày, giờ yên lặng).
#
# Mỗi lần xét (vòng lặp gọi mỗi nhịp, hoặc người dùng bấm "Tạo đánh giá hôm nay"):
# 1. nhắc lịch tập (buổi hôm nay, buổi bị lỡ) và đề xuất điều chỉnh khi điểm sẵn sàng thấp;
# 2. cảnh báo chỉ số: bộ luật (health_rules) → bỏ những gì đã báo hoặc đang trong thời gian chờ → chỉ khi đó
#    mới gọi LLM viết lời (composer), để không tốn lượt gọi ở mỗi nhịp;
# 3. đánh giá ngày: từ giờ người dùng chọn, một lần mỗi ngày (dedup_key review:<ngày>).
# Gửi xong, mỗi thông báo mới được phát qua WebSocket (realtime.publish, giao khi transaction commit).
# --------------------------------------------------------------------------------------------------

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
            await publish(session, user_id, "created", notification_id)
            if not draft.urgent:
                used += 1
    return created


async def _move_missed(session, user_id: UUID, plan, context: Context, local_now: datetime):
    """Tuỳ chọn "auto": dời từng buổi bị lỡ (chưa báo lần nào) sang ngày trống gần nhất; trả về lịch hiện hành."""
    for missed in list(context.missed):
        if await UserNotification.keys(session, user_id, [f"missed:{missed.entry_id}"]):
            continue
        target = free_day(plan, local_now.date())
        moved = target and await move_missed(session, user_id, plan, missed.entry_id, target)
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
        rank, since = health_rules.SEVERITY_RANK[signal.severity], today - timedelta(days=signal.meta.cooldown_days)
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
    plan = await current_plan(session, user.id)
    context = await gather(session, user.id, local_now, plan)
    if plan is not None and prefs.missed_session == "auto" and context.missed:
        plan = await _move_missed(session, user.id, plan, context, local_now)
    drafts = compose(context, prefs, local_now)

    wants_review = force or await review_due(session, user.id, prefs, local_now)
    alerts = health and prefs.health_alerts and bool(prefs.alert_groups)
    if not (health or wants_review):
        return await deliver(session, user.id, drafts, prefs, local_now, force=force)

    assessment = await daily_health.assess(session, user, zone=prefs.timezone, now=now)
    drafts += adjust(assessment, context, prefs)
    if not (alerts or wants_review):
        return await deliver(session, user.id, drafts, prefs, local_now, force=force)
    found, profile = await health_rules.gather(session, user, today, prefs.timezone)
    if alerts:
        signals = await fresh_signals(session, user.id, evaluate_rules(found, profile, prefs.alert_groups), today)
        budget = max(0, prefs.max_per_day - await UserNotification.count_for_day(session, user.id, today))
        for signal in signals:
            if signal.severity != "urgent":
                if budget <= 0:
                    continue
                budget -= 1
            drafts.append(await alert(session, user.id, signal, profile))
    if wants_review:
        sessions = [(item.label, False) for item in context.today] + [(item.label, True) for item in context.done_today]
        scored = analytics_services.review(found, profile, readiness_score=getattr(assessment, "score", None),
                                   sessions=sessions)
        titles = await UserNotification.titles(session, user.id, "alert", today)
        titles += [draft.title for draft in drafts if draft.kind == "alert"]
        drafts.append(await review(session, user.id, scored, profile, alerts=titles,
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
        await publish(session, user_id, "seen", notification_id)
    return NotificationRead.model_validate(found)


async def dismiss(session, user_id: UUID, notification_id: UUID) -> None:
    found = await _owned(session, user_id, notification_id)
    if found.dismissed_at is None:
        found.dismissed_at = _now()
        found.seen_at = found.seen_at or found.dismissed_at
        await session.flush()
        await publish(session, user_id, "dismissed", notification_id)


# --------------------------------------------------------------------------------------------------
# Lập lịch thông báo: mỗi nhịp tiêu thụ sự kiện `health.synced` rồi xét thông báo của mọi người dùng đã bật
# thông báo chủ động: nhắc lịch tập ở mọi nhịp; cảnh báo chỉ số khi có dữ liệu thiết bị mới, mỗi giờ một lần, hoặc
# lúc tới giờ đánh giá ngày (khi đó đồng bộ thiết bị trước nếu dữ liệu đã cũ để có số bước, phút vận động mới nhất).
#
# Chạy trong lifespan của API (như vòng đồng bộ Google Health). Nhiều tiến trình cùng chạy vẫn an toàn:
# khoá advisory cho phần tiêu thụ sự kiện, và dedup_key duy nhất cho phần tạo thông báo.
# --------------------------------------------------------------------------------------------------

CONSUMER = "backend.daily_briefing"
# Đồng bộ cũ hơn chừng này lúc tới giờ đánh giá ngày thì đồng bộ ngay để có số liệu mới nhất trong ngày.
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
                prefs = await preferences(session, user)
                local_now = now.astimezone(ZoneInfo(prefs.timezone))
                due = await review_due(session, user_id, prefs, local_now)
                hourly = local_now.minute < settings.DAILY_BRIEFING_POLL_MINUTES
                health = user_id in synced or due or hourly
                if due and user_id not in synced:
                    status = await ports.provider_status(session, user_id)
                    refresh = bool(status is not None and status.connected and (
                        status.last_success_at is None or now - status.last_success_at > REFRESH_IF_OLDER))
            if refresh:
                await ports.refresh(user_id)
            # Nhắc lịch tập (buổi hôm nay, buổi bị lỡ) được xét ở mọi nhịp.
            async with get_db_session() as session:
                created += len(await evaluate(session, await session.get(User, user_id), now=now,
                                                    health=health))
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


# --------------------------------------------------------------------------------------------------
# Đẩy thông báo tức thì qua WebSocket: /api/v2/notifications/stream.
#
# Phát: `publish` gọi pg_notify trong transaction của bên ghi, nên PostgreSQL chỉ giao sự kiện khi thay đổi đã
# commit (rollback thì không có gì). Payload chỉ có định danh {user, id, event}, không có nội dung sức khoẻ.
#
# Nhận: mỗi tiến trình backend có một kết nối psycopg autocommit LISTEN kênh này (`listen_loop`). Tiến trình nào
# đang giữ socket của người dùng đó thì đọc dòng thông báo và đẩy xuống (`Hub`). Mất kết nối DB thì nối lại có
# giãn cách và báo `resync` để client tải lại hộp thư (có thể đã lỡ sự kiện trong lúc mất kết nối).
#
# Xác thực: tin nhắn đầu tiên {"type": "auth", "token": "<access token>"} trong AUTH_TIMEOUT giây; token không
# nằm trong URL (URL bị ghi log). Chỉ access token của người dùng (token uỷ quyền của trợ lý khác audience nên
# bị từ chối). Socket đóng 4401 khi token hết hạn để client làm mới token rồi nối lại.
# --------------------------------------------------------------------------------------------------

CHANNEL = "hercfit_notifications"
EVENTS = ("created", "seen", "dismissed")
AUTH_TIMEOUT = 10.0
PING_SECONDS = 30.0
MAX_SOCKETS = 5
QUEUE_SIZE = 64
UNAUTHORIZED, TOO_MANY = 4401, 4429


async def publish(session, user_id: UUID, event: str, notification_id: UUID) -> None:
    """Giao khi transaction của `session` commit (NOTIFY trong transaction)."""
    if event not in EVENTS:
        raise ValueError(f"Unknown notification event {event!r}")
    payload = json.dumps({"user": str(user_id), "id": str(notification_id), "event": event})
    await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": payload})


class Hub:
    """Các socket đang mở của tiến trình này, theo người dùng."""

    def __init__(self) -> None:
        self._queues: dict[UUID, set[asyncio.Queue]] = {}

    def count(self, user_id: UUID) -> int:
        return len(self._queues.get(user_id, ()))

    @contextmanager
    def subscribe(self, user_id: UUID) -> Iterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(QUEUE_SIZE)
        self._queues.setdefault(user_id, set()).add(queue)
        try:
            yield queue
        finally:
            queues = self._queues.get(user_id, set())
            queues.discard(queue)
            if not queues:
                self._queues.pop(user_id, None)

    def push(self, user_id: UUID, message: dict[str, Any]) -> None:
        for queue in list(self._queues.get(user_id, ())):
            _offer(queue, message)

    def broadcast(self, message: dict[str, Any]) -> None:
        for queues in list(self._queues.values()):
            for queue in list(queues):
                _offer(queue, message)


def _offer(queue: asyncio.Queue, message: dict[str, Any]) -> None:
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:  # client quá chậm: bỏ hàng đợi, bảo nó tải lại toàn bộ
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait({"type": "resync"})


hub = Hub()


async def message_for(session, user_id: UUID, event: str, notification_id: UUID) -> dict[str, Any] | None:
    from domains.notifications.models import UserNotification
    from domains.notifications.schemas import NotificationRead

    found = await UserNotification.owned(session, user_id, notification_id)
    if found is None:
        return None
    unread = await UserNotification.unread_count(session, user_id, now=datetime.now(timezone.utc))
    if event == "created":
        return {"type": "notification.created", "unread": unread,
                "notification": NotificationRead.model_validate(found).model_dump(mode="json")}
    if event == "seen":
        return {"type": "notification.seen", "id": str(notification_id), "unread": unread,
                "seen_at": found.seen_at.isoformat() if found.seen_at else None}
    return {"type": "notification.dismissed", "id": str(notification_id), "unread": unread}


async def dispatch(target: Hub, payload: str) -> None:
    try:
        data = json.loads(payload)
        user_id, notification_id, event = UUID(data["user"]), UUID(data["id"]), data["event"]
    except (ValueError, KeyError, TypeError):
        return
    if event not in EVENTS or not target.count(user_id):
        return
    async with get_db_session() as session:
        message = await message_for(session, user_id, event, notification_id)
    if message is not None:
        target.push(user_id, message)


async def listen_loop(target: Hub = hub) -> None:
    import psycopg

    delay, connected_before = 1.0, False
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(get_postgres_connection_string(),
                                                             autocommit=True) as connection:
                await connection.execute(f"LISTEN {CHANNEL}")
                if connected_before:
                    target.broadcast({"type": "resync"})
                connected_before, delay = True, 1.0
                async for notify in connection.notifies():
                    try:
                        await dispatch(target, notify.payload)
                    except Exception as exc:  # một sự kiện lỗi không dừng vòng nghe
                        logger.warning("notification_dispatch_error error=%s", type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("notification_listen_error error=%s retry_in=%s", type(exc).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


# ---------------------------------------------------------------------------- socket

async def _close(websocket, code: int) -> None:
    with suppress(Exception):
        await websocket.close(code=code)


async def authenticate(websocket) -> tuple[UUID, float] | None:
    """(user_id, exp) từ tin nhắn đầu tiên, hoặc None khi không hợp lệ hay quá hạn chờ."""
    from core.security import decode_access_token

    try:
        message = json.loads(await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT))
        if not isinstance(message, dict) or message.get("type") != "auth":
            return None
        claims = decode_access_token(str(message.get("token") or ""))
        return UUID(str(claims["sub"])), float(claims["exp"])
    except (asyncio.TimeoutError, ValueError, KeyError, TypeError, HTTPException):
        return None
    except Exception:  # client ngắt kết nối trước khi xác thực
        return None


async def _sender(websocket, queue: asyncio.Queue) -> None:
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), PING_SECONDS)
        except asyncio.TimeoutError:
            message = {"type": "ping"}
        await websocket.send_json(message)


async def _receiver(websocket) -> None:
    while True:  # client chỉ gửi "pong"; vòng này chủ yếu để phát hiện ngắt kết nối
        await websocket.receive_text()


async def stream(websocket, target: Hub = hub) -> None:
    from domains.identity.models import User
    from domains.notifications.models import UserNotification

    await websocket.accept()
    identity = await authenticate(websocket)
    if identity is None:
        await _close(websocket, UNAUTHORIZED)
        return
    user_id, expires = identity
    async with get_db_session() as session:
        user = await User.get_by_id(session, user_id)
        unread = await UserNotification.unread_count(session, user_id, now=datetime.now(timezone.utc)) \
            if user is not None and user.is_active else None
    if unread is None:
        await _close(websocket, UNAUTHORIZED)
        return
    if target.count(user_id) >= MAX_SOCKETS:
        await _close(websocket, TOO_MANY)
        return
    with target.subscribe(user_id) as queue:
        await websocket.send_json({"type": "ready", "unread": unread})
        tasks = {asyncio.create_task(_sender(websocket, queue)), asyncio.create_task(_receiver(websocket))}
        done, pending = await asyncio.wait(tasks, timeout=max(1.0, expires - datetime.now(timezone.utc).timestamp()),
                                           return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if not task.cancelled():
                task.exception()  # lấy lỗi ra để asyncio không cảnh báo: lỗi ở đây là client đã ngắt kết nối
        if not done:
            await _close(websocket, UNAUTHORIZED)  # token hết hạn: client làm mới rồi nối lại


# --------------------------------------------------------------------------------------------------
# Nhắc lịch tập: nhắc buổi tập, buổi bị lỡ và đề xuất điều chỉnh buổi tập khi điểm sẵn sàng thấp.
#
# Phần soạn (`compose`) là hàm thuần trên một `Context` đã thu thập; câu chữ do code sinh, không gọi LLM.
# dedup_key quyết định "đã báo chưa":
#
# * nhắc buổi tập: một lần mỗi ngày có buổi chưa ghi nhận, từ giờ nhắc người dùng chọn;
# * buổi bị lỡ (3 ngày gần nhất, chưa ghi nhận): "ask" đề xuất dời sang ngày trống gần nhất (người dùng xác
#   nhận qua trợ lý); "auto" đã được dời trước khi soạn (`move_missed`), ở đây chỉ báo lại; "none" im lặng;
# * điều chỉnh (một lần mỗi ngày): điểm sẵn sàng dưới ngưỡng người dùng chọn trong ngày có buổi tập chưa ghi
#   nhận: đề xuất đổi sang buổi nhẹ. Chỉ là lời mời; mọi thay đổi lịch vẫn đi qua trợ lý và thẻ xác nhận.
# --------------------------------------------------------------------------------------------------

MISSED_LOOKBACK_DAYS = 3
WEEKDAYS = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật")
ACTIVE_STATES = {"ready", "steady", "ease_off", "recover"}


@dataclass(frozen=True)
class Session:
    entry_id: str
    plan_id: str
    label: str
    day: date
    exercises: int


@dataclass
class Context:
    today: list[Session] = field(default_factory=list)
    # Buổi của hôm nay đã ghi nhận (cho đánh giá ngày).
    done_today: list[Session] = field(default_factory=list)
    tomorrow: list[Session] = field(default_factory=list)
    missed: list[Session] = field(default_factory=list)
    # Ngày trống gần nhất (từ hôm nay tới hết lịch) để đề xuất dời buổi bị lỡ.
    free_day: date | None = None
    moved: list[tuple[Session, date]] = field(default_factory=list)


def day_label(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d/%m}"


def _reminder(context: Context, prefs: NotificationPreferences, local_now: datetime) -> list[Draft]:
    if not prefs.workout_reminder or not context.today or local_now.time() < clock(prefs.workout_reminder_time):
        return []
    first = context.today[0]
    more = f" và {len(context.today) - 1} buổi khác" if len(context.today) > 1 else ""
    count = f" · {first.exercises} bài tập" if first.exercises else ""
    return [Draft("reminder", "WORKOUT_REMINDER", 2, f"reminder:workout:{local_now.date().isoformat()}",
                  "Đến giờ tập rồi", f"Hôm nay bạn có buổi {first.label}{count}{more}. Tập xong nhớ ghi nhận trong "
                  "Dashboard hoặc nhắn cho trợ lý.", {"entry_id": first.entry_id, "plan_id": first.plan_id},
                  ttl_days=1)]


def adjust(assessment: Any, context: Context, prefs: NotificationPreferences) -> list[Draft]:
    """Đề xuất điều chỉnh buổi tập hôm nay khi điểm sẵn sàng thấp hơn ngưỡng người dùng chọn."""
    session = context.today[0] if context.today else None
    score = getattr(assessment, "score", None)
    if (session is None or not prefs.adjust_on_low_readiness or score is None
            or assessment.state not in ACTIVE_STATES or score >= prefs.readiness_threshold):
        return []
    ask = (f"Điểm sẵn sàng hôm nay của mình là {score}/100. Điều chỉnh giúp buổi {session.label} hôm nay "
           "thành buổi nhẹ hơn hoặc buổi phục hồi.")
    return [Draft("proposal", "READINESS_ADJUST", 1, f"proposal:readiness:{assessment.date.isoformat()}",
                  "Đề xuất điều chỉnh buổi tập",
                  f"Điểm sẵn sàng hôm nay là {score}/100, thấp hơn ngưỡng {prefs.readiness_threshold}. "
                  f"Bạn có muốn chuyển {session.label} sang buổi phục hồi nhẹ không?",
                  {"date": assessment.date.isoformat(), "state": assessment.state,
                   "algorithm_version": assessment.algorithm_version, "score": score,
                   "threshold": prefs.readiness_threshold, "entry_id": session.entry_id, "ask": ask}, ttl_days=1)]


def _missed(context: Context, prefs: NotificationPreferences) -> list[Draft]:
    drafts = []
    for session, moved_to in context.moved:
        drafts.append(Draft("proposal", "MISSED_MOVED", 2, f"missed:{session.entry_id}", "Đã dời buổi tập bị lỡ",
                            f"Buổi {session.label} ({day_label(session.day)}) chưa được ghi nhận nên đã được dời sang "
                            f"{day_label(moved_to)} theo cài đặt của bạn.",
                            {"entry_id": session.entry_id, "moved_to": moved_to.isoformat()}, ttl_days=3))
    if prefs.missed_session != "ask":
        return drafts
    for session in context.missed:
        target = f" sang {day_label(context.free_day)}" if context.free_day else ""
        ask = (f"Mình đã lỡ buổi {session.label} ngày {session.day:%d/%m}. Dời giúp mình buổi này{target} "
               "trong lịch tập.")
        drafts.append(Draft("proposal", "MISSED_SESSION", 2, f"missed:{session.entry_id}", "Bạn đã lỡ một buổi tập",
                            f"Buổi {session.label} ({day_label(session.day)}) đã qua ngày mà chưa được ghi nhận. "
                            f"Bạn có muốn dời buổi này{target} không?",
                            {"entry_id": session.entry_id, "plan_id": session.plan_id, "ask": ask,
                             "suggested_date": context.free_day.isoformat() if context.free_day else None},
                            ttl_days=3))
    return drafts


def compose(context: Context, prefs: NotificationPreferences, local_now: datetime) -> list[Draft]:
    """Các nhắc lịch tập nên có tại local_now (giờ địa phương), theo thứ tự ưu tiên."""
    return sorted(_missed(context, prefs) + _reminder(context, prefs, local_now), key=lambda draft: draft.priority)


# ------------------------------------------------------------------------------ đọc dữ liệu

def _session(entry: Any, plan: Any) -> Session:
    return Session(entry_id=str(entry.id), plan_id=str(plan.id), label=entry.label, day=entry.scheduled_date,
                   exercises=len(entry.items or []))


def free_day(plan: Any, start: date) -> date | None:
    """Ngày đầu tiên từ `start` tới hết lịch không có buổi tập nào (buổi nghỉ hoặc không có buổi)."""
    busy = {entry.scheduled_date for entry in plan.entries if not entry.is_rest}
    day = start
    while day <= plan.end_date:
        if day not in busy:
            return day
        day += timedelta(days=1)
    return None


async def current_plan(session, user_id: UUID):
    from domains.goals_plans.models import TrainingPlan

    return await TrainingPlan.get_current_for_user(session, user_id=user_id)


async def gather(session, user_id: UUID, local_now: datetime, plan: Any = None) -> Context:
    today = local_now.date()
    context = Context()
    if plan is not None:
        sessions = [entry for entry in plan.entries if not entry.is_rest]
        pending = [entry for entry in sessions if entry.completed_at is None]
        context.today = [_session(entry, plan) for entry in pending if entry.scheduled_date == today]
        context.done_today = [_session(entry, plan) for entry in sessions
                              if entry.scheduled_date == today and entry.completed_at is not None]
        context.tomorrow = [_session(entry, plan) for entry in sessions
                            if entry.scheduled_date == today + timedelta(days=1)]
        context.missed = [_session(entry, plan) for entry in pending
                          if today - timedelta(days=MISSED_LOOKBACK_DAYS) <= entry.scheduled_date < today]
        context.free_day = free_day(plan, today)
    return context


async def move_missed(session, user_id: UUID, plan: Any, entry_id: str, target: date) -> Any | None:
    """Dời một buổi bị lỡ sang `target` bằng một phiên bản lịch mới (như khi người dùng sửa lịch).

    Trả về lịch mới, hoặc None khi không dời được (bài không còn trong catalog, lịch đã đổi...)."""
    from fastapi import HTTPException

    from domains.goals_plans.models import TrainingPlan

    entries = []
    for entry in plan.entries:
        if any(item.exercise_id is None for item in entry.items or []):
            return None
        if entry.is_rest and entry.scheduled_date == target:
            continue  # buổi tập dời tới thay cho ngày nghỉ đó
        entries.append({
            "scheduled_date": target if str(entry.id) == entry_id else entry.scheduled_date,
            "scheduled_time": entry.scheduled_time, "label": entry.label, "note": entry.note,
            "is_rest": entry.is_rest,
            "items": [{"exercise_id": item.exercise_id, "prescription": item.prescription, "note": item.note}
                      for item in entry.items or []],
        })
    payload = {"name": plan.name, "start_date": plan.start_date, "end_date": max(plan.end_date, target),
               "note": plan.note, "entries": entries}
    try:
        return await TrainingPlan.replace_for_user(session, plan.id, user_id=user_id, payload=payload,
                                                   expected_version_id=plan.version_id)
    except (HTTPException, ValueError):
        return None
