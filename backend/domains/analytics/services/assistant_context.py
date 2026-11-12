"""Ảnh chụp gọn, tất định về những gì HercFit biết về người dùng, dành cho trợ lý.

Một request cho trợ lý các dữ kiện mà nếu không nó sẽ phải hỏi người dùng (tuổi, cơ thể,
mục tiêu, hồ sơ vận động viên, chạy bộ và tập luyện gần đây) cộng danh mục dữ liệu đã ghi, để nó
cá nhân hoá câu trả lời và đọc chi tiết bằng tool thay vì hỏi. Mọi giá trị đều được
tính tại đây từ bản ghi đã lưu; trợ lý không bao giờ tính lại hay bịa ra chúng.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from sqlalchemy import func, select

from domains.body.models.body_metrics import BodyMetric
from domains.goals_plans.models.goal import Goal
from domains.health_records import ports
from domains.health_records.services.health_service import measured_resting_hr
from domains.identity import consent
from domains.nutrition.models.meals import Meal
from domains.training.models.trainings import Training
from domains.training.schemas.training import AnalyticsQuery
from domains.training.services import training_analytics as analytics

RUN_WEEKS = 8
RECENT_WEEKS = 4


def _float(value) -> float | None:
    return round(float(value), 2) if value is not None else None


async def _height(session, user_id, device_allowed: bool) -> float | None:
    """Chiều cao hiếm khi được đo; lấy số đo mới nhất có chiều cao, không phải số đo mới nhất."""
    latest = await BodyMetric.latest(session, user_id, "height_cm", respect_consent=not device_allowed)
    return _float(latest.height_cm) if latest is not None else None


async def _count(session, model, user_id, column, since: datetime) -> int:
    return (await session.execute(select(func.count()).select_from(model).where(
        model.user_id == user_id, column >= since, *([model.is_active.is_(True)] if hasattr(model, 'is_active') else []),
    ))).scalar_one()


def _running(summary: dict[str, Any], last_run) -> dict[str, Any]:
    weeks = summary["weeks"]
    recent = weeks[-RECENT_WEEKS:]
    distance = sum(float(w["distance_meters"]) for w in recent)
    duration = sum(float(w["duration_seconds"]) for w in recent)
    return {
        "window_weeks": RUN_WEEKS,
        "runs": sum(w["runs"] for w in weeks),
        "weeks_with_runs": sum(1 for w in weeks if w["runs"]),
        "avg_weekly_km_4w": round(distance / 1000 / len(recent), 1) if recent else None,
        "avg_weekly_runs_4w": round(sum(w["runs"] for w in recent) / len(recent), 1) if recent else None,
        "avg_pace_s_per_km_4w": round(duration * 1000 / distance) if distance else None,
        "longest_run_km": round(max((float(w["longest_run_meters"]) for w in weeks), default=0) / 1000, 2) or None,
        "easy_share_pct": summary["easy_share_pct"],
        "pace_by_workout_type_s_per_km": summary["pace_by_workout_type"],
        "best_efforts": summary["best_efforts_seconds"],
        "race_predictions_seconds": summary["race_predictions_seconds"],
        "last_run": last_run,
    }


async def build(session, user, *, timezone: str, agent: bool | None = None) -> dict[str, Any]:
    """`agent` bị bỏ qua: ai đọc là principal của request (core.principal), được kiểm tra theo consent."""
    today = analytics.today_in(timezone)
    now = datetime.now(dt_timezone.utc)
    provider = await ports.provider_status(session, user.id)
    decision = await consent.load(session, user.id)
    # Trợ lý chỉ dùng dữ liệu thiết bị khi người dùng cho phép (cùng luật trên mọi đường đọc).
    device_allowed = await consent.device_access(session, user.id)
    measured = await measured_resting_hr(session, user.id, today) if device_allowed else None
    athlete = analytics.profile_read(user.personal_info, measured)
    profile = athlete["profile"]

    latest = await BodyMetric.get_latest_for_user(session, user_id=user.id)
    goal = await Goal.get_current_for_user(session, user_id=user.id)

    window = AnalyticsQuery(start_date=today - timedelta(days=7 * RUN_WEEKS - 1), end_date=today, timezone=timezone)
    running = await analytics.running_summary(session, user.id, window, profile)
    recent = await analytics.recent_runs(session, user.id, today - timedelta(days=29), today, timezone, limit=1)
    four_weeks = AnalyticsQuery(start_date=today - timedelta(days=27), end_date=today, timezone=timezone)
    load = await analytics.load(session, user.id, AnalyticsQuery(start_date=today, end_date=today, timezone=timezone))
    weekly = (await analytics.summary(session, user.id, four_weeks))["weeks"]

    context = {
        "generated_at": now.isoformat(), "timezone": timezone, "today": today.isoformat(),
        "profile": {"age": user.age, "sex": user.sex},
        "body": {
            "weight_kg": _float(latest.weight_kg) if latest else None,
            "height_cm": await _height(session, user.id, device_allowed),
            "body_fat_pct": _float(latest.body_fat_pct) if latest else None,
            "measured_at": latest.recorded_at.isoformat() if latest else None,
        },
        "goal": {"title": goal.title, "goal_types": goal.goal_types, "target_date": goal.target_date.isoformat()
                 if goal.target_date else None, "targets": goal.targets} if goal else None,
        "athlete": {
            "configured": athlete["configured"], "experience_level": profile.experience_level,
            "primary_focus": profile.primary_focus, "available_days": profile.available_days,
            "session_minutes": profile.session_minutes, "injuries": profile.injuries, "equipment": profile.equipment,
            "max_hr": profile.max_hr, "resting_hr": profile.resting_hr or measured,
            "resting_hr_source": athlete["resting_hr_source"],
            "threshold_pace_s_per_km": profile.threshold_pace_s_per_km,
            "recent_race": profile.recent_race.model_dump(mode="json") if profile.recent_race else None,
        },
        "running": _running(running, recent[0] if recent else None),
        "training_4w": {
            "sessions": sum(w["sessions"] for w in weekly),
            "sessions_by_discipline": {key: sum(w["sessions_by_discipline"].get(key, 0) for w in weekly)
                                       for key in sorted({k for w in weekly for k in w["sessions_by_discipline"]})},
            "acwr": load["days"][-1]["acwr"] if load["days"] else None,
            "sessions_without_rpe": load["sessions_without_rpe"],
        },
        "inventory": {
            "trainings_60d": await _count(session, Training, user.id, Training.started_at, now - timedelta(days=60)),
            "meals_14d": await _count(session, Meal, user.id, Meal.consumed_at, now - timedelta(days=14)),
            "body_metrics": (await session.execute(select(func.count()).select_from(BodyMetric).where(
                BodyMetric.user_id == user.id, BodyMetric.is_active.is_(True),
                *([] if device_allowed else [BodyMetric.source == "MANUAL"])))).scalar_one(),
            "health_connected": provider is not None,
            "health_shared_with_assistant": decision.device,
        },
    }
    context["missing"] = missing(context)
    return context


# Các dữ kiện huấn luyện viên cần; được liệt kê khi thiếu để trợ lý chỉ hỏi những thứ này.
def missing(context: dict[str, Any]) -> list[str]:
    checks = {
        "age": context["profile"]["age"], "sex": context["profile"]["sex"],
        "weight": context["body"]["weight_kg"], "height": context["body"]["height_cm"],
        "goal": context["goal"], "athlete_profile": context["athlete"]["configured"] or None,
        "recent_race": context["athlete"]["recent_race"] or context["running"]["best_efforts"] or None,
        "running_history": context["running"]["runs"] or None, "max_hr": context["athlete"]["max_hr"],
    }
    return [name for name, value in checks.items() if value in (None, [], {})]
