"""Nhắc lịch tập: nhắc buổi tập, buổi bị lỡ và đề xuất điều chỉnh buổi tập khi điểm sẵn sàng thấp.

Phần soạn (`compose`) là hàm thuần trên một `Context` đã thu thập; câu chữ do code sinh, không gọi LLM.
dedup_key quyết định "đã báo chưa":

* nhắc buổi tập: một lần mỗi ngày có buổi chưa ghi nhận, từ giờ nhắc người dùng chọn;
* buổi bị lỡ (3 ngày gần nhất, chưa ghi nhận): "ask" đề xuất dời sang ngày trống gần nhất (người dùng xác
  nhận qua trợ lý); "auto" đã được dời trước khi soạn (`move_missed`), ở đây chỉ báo lại; "none" im lặng;
* điều chỉnh (một lần mỗi ngày): điểm sẵn sàng dưới ngưỡng người dùng chọn trong ngày có buổi tập chưa ghi
  nhận: đề xuất đổi sang buổi nhẹ. Chỉ là lời mời; mọi thay đổi lịch vẫn đi qua trợ lý và thẻ xác nhận.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from domains.notifications.schemas.notification import NotificationPreferences
from domains.notifications.services.drafts import Draft, clock

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
    from domains.goals_plans.models.plans import TrainingPlan

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

    from domains.goals_plans.models.plans import TrainingPlan

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
