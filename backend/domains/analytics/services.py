"""Service nghiệp vụ của miền phân tích."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import Date, case, func, select

from domains.analytics import daily_health, health_rules
from domains.analytics.health_rules import Features, Profile, hm, vn
from domains.analytics.schemas import (
    DailyProgressRead,
    MetricProgress,
    PlanProgressRead,
    ProgressRead,
)
from domains.body.models import BodyMetric
from domains.catalog.schemas import NUTRIENT_FIELDS
from domains.goals_plans.models import Goal, Plan
from domains.health_records import ports, views
from domains.health_records.schemas import HEALTH_PROVIDER, HealthOverviewQuery
from domains.health_records.services import measured_resting_hr
from domains.identity import consent
from domains.nutrition.models import Meal, MealItem
from domains.shared.schemas import DateRangeQuery
from domains.training import services as analytics
from domains.training.models import Training, TrainingItem
from domains.training.schemas import AnalyticsQuery

# --------------------------------------------------------------------------------------------------
# Ảnh chụp gọn, tất định về những gì HercFit biết về người dùng, dành cho trợ lý.
#
# Một request cho trợ lý các dữ kiện mà nếu không nó sẽ phải hỏi người dùng (tuổi, cơ thể,
# mục tiêu, hồ sơ vận động viên, chạy bộ và tập luyện gần đây) cộng danh mục dữ liệu đã ghi, để nó
# cá nhân hoá câu trả lời và đọc chi tiết bằng tool thay vì hỏi. Mọi giá trị đều được
# tính tại đây từ bản ghi đã lưu; trợ lý không bao giờ tính lại hay bịa ra chúng.
# --------------------------------------------------------------------------------------------------

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


async def build_assistant_context(session, user, *, timezone: str, agent: bool | None = None) -> dict[str, Any]:
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


# --------------------------------------------------------------------------------------------------
# Context API của trợ lý: các con số tính sẵn, có nguồn, trong một ngân sách token.
#
# Mỗi mục là {key, label, value, unit, source, measured_at, freshness_s, coverage,
# method, algorithm_version, evidence}. Trợ lý đọc các con số này; nó không bao giờ
# tính lại tổng, đường nền hay chỉ số từ hàng nghìn mẫu.
#
# Các luật áp dụng cho mọi chủ đề:
# * mục đo bởi thiết bị cần consent `device` của bên đọc; mục nhạy cảm
#   (đường huyết, phân loại ECG/IRN) cần consent `sensitive` riêng; kiểm tra ở mỗi lần dựng.
# * dạng sóng ECG, lộ trình GPS và token không bao giờ thuộc một ngữ cảnh.
# * dữ liệu thiếu được nêu rõ (trạng thái độ phủ), không bao giờ là số 0 hay phỏng đoán.
# * ngữ cảnh được dựng mỗi lần đọc từ health_points (nhanh, không có bảng cache), nên luôn
#   khớp quyết định consent hiện tại.
# --------------------------------------------------------------------------------------------------

TOPICS = ("overview", "activity", "sleep", "recovery", "body", "nutrition", "vitals")
SENSITIVE_TOPICS = {"vitals"}
PERIODS = {"7d": 7, "28d": 28, "90d": 90}
BASE_BUDGET = 1500
DEEP_BUDGET = 4000
METHOD_VERSION = "context-v2"


def tokens(value: Any) -> int:
    """Ước lượng thô số token (JSON UTF-8 / 4): rẻ, tất định, hơi bi quan với tiếng Việt."""
    return len(json.dumps(value, ensure_ascii=False, default=str).encode()) // 4 + 1


def item(key: str, label: str, value: Any, unit: str | None, *, source: str, measured_at: Any = None,
         coverage: dict[str, Any] | None = None, method: str, evidence: list[dict[str, str]] | None = None,
         now: datetime | None = None, algorithm_version: str = METHOD_VERSION,
         today: date | None = None) -> dict[str, Any]:
    """today: ngày địa phương của người dùng, để độ mới của một mục theo ngày không lệch theo UTC."""
    now = now or datetime.now(timezone.utc)
    stamp = measured_at
    freshness = None
    if isinstance(measured_at, datetime):
        freshness = int((now - measured_at).total_seconds())
        stamp = measured_at.isoformat()
    elif isinstance(measured_at, date):
        freshness = ((today or now.date()) - measured_at).days * 86400
        stamp = measured_at.isoformat()
    return {"key": key, "label": label, "value": value, "unit": unit, "source": source, "measured_at": stamp,
            "freshness_s": freshness, "coverage": coverage, "method": method, "algorithm_version": algorithm_version,
            "evidence": evidence or []}


def _round(value: Any, digits: int = 1) -> Any:
    return round(float(value), digits) if value is not None else None


def _last_observed(report: dict[str, Any], column: str) -> date | None:
    """Ngày gần nhất thật sự có dữ liệu của cột: thời điểm đo của một mục tổng hợp, không phải ngày kết thúc."""
    days = [day for day, state in ((report.get(column) or {}).get("by_day") or {}).items() if state in ("OBSERVED", "ZERO")]
    return date.fromisoformat(max(days)) if days else None


def _coverage(report: dict[str, Any], column: str) -> dict[str, Any]:
    entry = report.get(column) or {}
    return {"state": entry.get("state", "NO_DATA"), "observed_days": entry.get("observed_days", 0),
            "days": entry.get("days", 0)}


async def _overview(session, user, period_days: int, zone: str):
    from domains.health_records.services import HealthService

    service = HealthService(session, user)
    return await service.overview(HealthOverviewQuery(days=period_days, timezone=zone))


async def build_context(session, user, *, topic: str, period: str, zone: str, now: datetime | None = None) -> dict[str, Any]:
    if topic not in TOPICS or period not in PERIODS:
        raise ValueError("unknown topic or period")
    now = now or datetime.now(timezone.utc)
    days = PERIODS[period]
    decision = await consent.load(session, user.id)
    device = await consent.device_access(session, user.id)
    sensitive = await consent.device_access(session, user.id, "sensitive")
    end = now.astimezone(ZoneInfo(zone)).date()
    start = end - timedelta(days=days - 1)
    items: list[dict[str, Any]] = []
    withheld: list[str] = []
    if topic in SENSITIVE_TOPICS and not sensitive:
        return {"topic": topic, "period": period, "items": [], "withheld": [topic], "consent_version": decision.version}
    report = await daily_health.coverage(session, user.id, start, end) if device else {}

    if topic in ("overview", "body"):
        metrics = await BodyMetric.list_for_user(session, user_id=user.id, limit=20)
        latest = next((m for m in metrics if m.weight_kg is not None), None)
        if latest is not None:
            items.append(item("body.weight", "Cân nặng gần nhất", _round(latest.weight_kg, 2), "kg",
                              source=latest.source, measured_at=latest.recorded_at, method="latest weigh-in",
                              evidence=[{"id": str(latest.id)}], now=now, today=end))
        height = next((m for m in metrics if m.height_cm is not None), None)
        if height is not None:
            items.append(item("body.height", "Chiều cao", _round(height.height_cm, 1), "cm", source=height.source,
                              measured_at=height.recorded_at, method="latest measurement",
                              evidence=[{"id": str(height.id)}], now=now, today=end))
        if not device:
            withheld.append("device_body_metrics")
    if device and topic in ("overview", "activity", "sleep", "recovery", "nutrition"):
        overview = await _overview(session, user, days, zone)
        a, s, r, e = overview.activity, overview.sleep, overview.recovery, overview.energy
        if topic in ("overview", "activity"):
            items += [
                item("activity.steps_avg", "Bước chân trung bình/ngày", _round(a.steps_avg, 0), "steps",
                     source=HEALTH_PROVIDER, measured_at=_last_observed(report, "steps"), coverage=_coverage(report, "steps"),
                     method=f"mean of observed days in {days}d", now=now, today=end),
                item("activity.active_minutes_week", "Phút vận động vừa–mạnh/tuần", _round(a.active_minutes_week, 0),
                     "min", source=HEALTH_PROVIDER, measured_at=_last_observed(report, "active_minutes"),
                     coverage=_coverage(report, "active_minutes"),
                     method="moderate+vigorous minutes, weekly rate; WHO target 150", now=now, today=end),
                item("activity.device_workouts", "Buổi tập thể thao trên Google Health", a.workouts, "sessions",
                     source=HEALTH_PROVIDER, measured_at=end,
                     method=f"count in {days}d (watch, chat-logged sport and other apps; gym logs are separate)",
                     now=now, today=end),
            ]
        if topic in ("overview", "sleep"):
            items += [
                item("sleep.avg_minutes", "Ngủ trung bình/đêm", _round(s.avg_minutes, 0), "min", source=HEALTH_PROVIDER,
                     measured_at=_last_observed(report, "sleep_minutes"), coverage=_coverage(report, "sleep_minutes"),
                     method="mean minutes asleep of main sleeps (naps excluded)", now=now, today=end),
                item("sleep.efficiency", "Hiệu quả giấc ngủ", _round(s.efficiency_pct, 1), "%", source=HEALTH_PROVIDER,
                     measured_at=_last_observed(report, "sleep_minutes"), method="asleep / in-bed of main sleeps",
                     now=now, today=end),
            ]
            if topic == "sleep":
                nights = sorted((night for night in await views.sleep(session, user.id, start, end) if not night.is_nap),
                                key=lambda night: night.local_date, reverse=True)[:14]
                for night in nights:
                    items.append(item(f"sleep.night.{night.local_date}", "Đêm", {
                        "asleep": night.minutes_asleep, "deep": night.deep_minutes, "rem": night.rem_minutes,
                        "awake": night.awake_minutes, "efficiency": _round(night.efficiency_pct)}, "min",
                        source=HEALTH_PROVIDER, measured_at=night.end_at, method="provider sleep summary",
                        evidence=[{"id": str(night.id)}], now=now, today=end))
        if topic in ("overview", "recovery"):
            items += [
                item("recovery.resting_hr", "Nhịp tim nghỉ 7 ngày vs nền trước đó",
                     {"recent": _round(r.resting_hr_7d), "baseline": _round(r.resting_hr_baseline),
                      "elevated": r.resting_hr_elevated}, "bpm", source=HEALTH_PROVIDER,
                     measured_at=_last_observed(report, "resting_hr_bpm"), coverage=_coverage(report, "resting_hr_bpm"),
                     method="median of the last 7 days vs median of the earlier days; elevated if ≥5 bpm above",
                     now=now, today=end, algorithm_version=daily_health.COVERAGE_ALGORITHM_VERSION),
                item("recovery.hrv", "HRV 7 ngày vs nền trước đó",
                     {"recent": _round(r.hrv_7d), "baseline": _round(r.hrv_baseline), "suppressed": r.hrv_suppressed},
                     "ms", source=HEALTH_PROVIDER, measured_at=_last_observed(report, "hrv_ms"),
                     coverage=_coverage(report, "hrv_ms"),
                     method="median of the last 7 days vs median of the earlier days; suppressed if ≥15% below", now=now, today=end,
                     algorithm_version=daily_health.COVERAGE_ALGORITHM_VERSION),
            ]
        if topic in ("overview", "nutrition"):
            items.append(item("energy.balance", "Cân bằng năng lượng (ngày ghi đủ)",
                              {"intake": _round(e.intake_kcal_avg, 0), "device_out": _round(e.device_expenditure_kcal_avg, 0),
                               "balance": _round(e.balance_kcal_avg, 0), "complete_days": e.complete_days}, "kcal",
                              source="DERIVED", measured_at=end,
                              method="logged intake on complete days vs total energy out (Google total-calories "
                                     "+ manually logged sessions, which Google does not add)",
                              now=now, today=end))
        if topic == "nutrition":
            water = [row.hydration_ml for row in await views.daily(session, user.id, start, end, zone)
                     if row.hydration_ml is not None]
            if water:
                items.append(item("hydration.total", "Nước uống ghi nhận", _round(sum(water), 0), "ml",
                                  source=HEALTH_PROVIDER, measured_at=_last_observed(report, "hydration_ml"),
                                  coverage=_coverage(report, "hydration_ml"),
                                  method=f"sum of hydration logs on {len(water)} days in {days}d", now=now, today=end))
    elif not device and topic != "body":
        withheld.append("device_data")

    if topic == "vitals":
        for sample in sorted(await views.samples(session, user.id, start, end, "BLOOD_GLUCOSE"),
                             key=lambda sample: sample.measured_at, reverse=True)[:10]:
            items.append(item(f"vitals.glucose.{sample.id}", "Đường huyết", _round(sample.value, 1), sample.unit,
                              source=sample.source, measured_at=sample.measured_at, method="provider measurement",
                              evidence=[{"id": str(sample.id)}], now=now, today=end))
        for ecg in (await views.sessions(session, user.id, "electrocardiogram", start, end))[-5:]:
            items.append(item(f"vitals.ecg.{ecg['id']}", "ECG (kết luận của thiết bị)", ecg.get("resultClassification"),
                              None, source=HEALTH_PROVIDER, measured_at=ecg["started_at"],
                              method="provider classification, reported as-is (no diagnosis)",
                              evidence=[{"id": str(ecg["id"])}], now=now, today=end))
        for alert in (await views.sessions(session, user.id, "irregular-rhythm-notification", start, end))[-5:]:
            positive = sum(1 for window in alert.get("alertWindows") or [] if (window or {}).get("positive"))
            items.append(item(f"vitals.irn.{alert['id']}", "Cảnh báo nhịp bất thường", positive, "windows",
                              source=HEALTH_PROVIDER, measured_at=alert["started_at"], method="provider notification",
                              evidence=[{"id": str(alert["id"])}], now=now, today=end))
    return {"topic": topic, "period": period, "items": items, "withheld": withheld,
            "consent_version": decision.version}


def fit(context: dict[str, Any], budget: int) -> dict[str, Any]:
    """Giữ các mục theo thứ tự ưu tiên cho đến khi hết ngân sách; báo lại phần bị cắt."""
    kept, used = [], tokens({k: v for k, v in context.items() if k != "items"})
    for entry in context["items"]:
        cost = tokens(entry)
        if used + cost > budget:
            break
        kept.append(entry)
        used += cost
    return {**context, "items": kept, "truncated": len(context["items"]) - len(kept), "tokens": used,
            "budget": budget}


async def get_context(session, user, *, topic: str = "overview", period: str = "28d", budget: int = BASE_BUDGET,
              zone: str | None = None) -> dict[str, Any]:
    """Ngữ cảnh dựng theo quyết định consent hiện tại, cắt theo ngân sách token.

    zone None: múi giờ của tài khoản nhà cung cấp (ports.user_timezone), để "hôm nay" là ngày địa phương.
    """
    zone = await ports.user_timezone(session, user.id, zone)
    context = await build_context(session, user, topic=topic, period=period, zone=zone)
    return fit(json.loads(json.dumps(context, default=str)), budget)


# --------------------------------------------------------------------------------------------------
# Đánh giá chất lượng một ngày: hàm thuần, tất định, có phiên bản. LLM chỉ diễn giải kết quả này.
#
# Mỗi mặt được chấm 0–100 khi có dữ liệu, ngược lại là `missing` và không tính vào điểm tổng (không bao giờ
# coi dữ liệu thiếu là ngày tệ). Điểm tổng là trung bình có trọng số trên các mặt có dữ liệu, cần ít nhất 2 mặt.
# --------------------------------------------------------------------------------------------------

ALGORITHM_VERSION = "day-review-v1"
Rating = Literal["good", "fair", "poor", "missing"]
WEIGHTS = {"nutrition": 0.30, "activity": 0.25, "sleep": 0.25, "recovery": 0.10, "plan": 0.10}
LABELS = {"nutrition": "Dinh dưỡng", "activity": "Vận động", "sleep": "Giấc ngủ", "recovery": "Hồi phục",
          "plan": "Lịch tập"}
MIN_DIMENSIONS = 2
STEPS_TARGET = 7000
GRADES = ((85, "Rất tốt"), (70, "Tốt"), (50, "Trung bình"), (0, "Cần cải thiện"))
TIPS = {
    "nutrition": "Ngày mai ghi đủ các bữa và bám sát mục tiêu năng lượng, ưu tiên đạm trong mỗi bữa.",
    "activity": "Ngày mai thêm 20–30 phút đi bộ nhanh hoặc một buổi tập ngắn.",
    "sleep": "Tối nay đi ngủ sớm hơn 30 phút để bù giấc.",
    "recovery": "Ngày mai ưu tiên vận động nhẹ và nghỉ ngơi để cơ thể hồi phục.",
    "plan": "Sắp xếp lại buổi tập bị lỡ vào ngày trống gần nhất.",
}


@dataclass(frozen=True)
class Dimension:
    id: str
    score: int | None
    detail: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def rating(self) -> Rating:
        if self.score is None:
            return "missing"
        return "good" if self.score >= 80 else "fair" if self.score >= 55 else "poor"

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": LABELS[self.id], "score": self.score, "rating": self.rating,
                "detail": self.detail, "values": self.values}


@dataclass(frozen=True)
class DayReview:
    date: date
    dimensions: list[Dimension]
    score: int | None
    grade: str | None

    @property
    def enough(self) -> bool:
        return self.score is not None

    def weakest(self) -> Dimension | None:
        scored = [d for d in self.dimensions if d.score is not None]
        return min(scored, key=lambda d: d.score) if scored else None

    def as_dict(self) -> dict[str, Any]:
        return {"date": self.date.isoformat(), "score": self.score, "grade": self.grade,
                "algorithm_version": ALGORITHM_VERSION, "dimensions": [d.as_dict() for d in self.dimensions]}


def _band(ratio: float, steps: tuple[tuple[float, int], ...], last: int) -> int:
    return next((score for limit, score in steps if ratio <= limit), last)


def nutrition(features: Features, profile: Profile) -> Dimension:
    row = features.intake.get(features.today)
    if row is None or row.meals < 2 or row.kcal is None or not profile.target_kcal:
        return Dimension("nutrition", None, "Chưa ghi đủ bữa hôm nay.")
    energy = _band(abs(row.kcal / profile.target_kcal - 1), ((0.10, 100), (0.20, 75), (0.30, 50)), 25)
    parts = [f"ăn {vn(row.kcal)}/{vn(profile.target_kcal)} kcal"]
    values: dict[str, Any] = {"meals": row.meals, "kcal": round(row.kcal), "target_kcal": round(profile.target_kcal)}
    score = energy
    if row.protein_g is not None and profile.protein_target_g:
        ratio = row.protein_g / profile.protein_target_g
        protein = 100 if ratio >= 0.9 else 75 if ratio >= 0.75 else 50 if ratio >= 0.5 else 25
        score = round(0.6 * energy + 0.4 * protein)
        parts.append(f"đạm {vn(row.protein_g)}/{vn(profile.protein_target_g)} g")
        values.update(protein_g=round(row.protein_g), protein_target_g=round(profile.protein_target_g))
    return Dimension("nutrition", score, ", ".join(parts).capitalize() + f" ({row.meals} bữa).", values)


def activity(features: Features, profile: Profile) -> Dimension:
    row = features.health.get(features.today)
    azm = row.active_zone_minutes if row is not None else None
    steps = row.steps if row is not None else None
    if azm is None and steps is None:
        return Dimension("activity", None, "Chưa có dữ liệu vận động hôm nay.")
    daily = 60 if profile.minor else health_rules.ACTIVITY_MIN_PER_WEEK / 7
    scores, parts, values = [], [], {}
    if azm is not None:
        scores.append(min(100, round(azm / daily * 100)))
        parts.append(f"{vn(azm)} phút vận động vừa–mạnh (mục tiêu khoảng {vn(daily)} phút/ngày)")
        values.update(active_zone_minutes=azm, target_minutes=round(daily))
    if steps is not None:
        scores.append(min(100, round(steps / STEPS_TARGET * 100)))
        parts.append(f"{vn(steps)} bước")
        values.update(steps=steps, steps_target=STEPS_TARGET)
    return Dimension("activity", max(scores), ", ".join(parts).capitalize() + ".", values)


def sleep(features: Features, profile: Profile) -> Dimension:
    row = features.health.get(features.today)
    minutes = row.sleep_minutes if row is not None else None
    if minutes is None:
        return Dimension("sleep", None, "Chưa có dữ liệu giấc ngủ đêm qua.")
    low, high = profile.recommended_sleep
    short = low * 60 - minutes
    if short <= 0:
        score = 100 if minutes <= high * 60 + 60 else 70
    else:
        score = 70 if short <= 60 else 45 if short <= 120 else 20
    return Dimension("sleep", score, f"Đêm qua ngủ {hm(minutes)} (khuyến nghị {vn(low)}–{vn(high)} giờ).",
                     {"minutes": minutes, "recommended_hours": [low, high]})


def recovery(readiness_score: int | None) -> Dimension:
    if readiness_score is None:
        return Dimension("recovery", None, "Chưa có điểm sẵn sàng hôm nay.")
    return Dimension("recovery", int(readiness_score), f"Điểm sẵn sàng {readiness_score}/100.",
                     {"readiness_score": readiness_score})


def plan(sessions: list[tuple[str, bool]]) -> Dimension:
    if not sessions:
        return Dimension("plan", None, "Hôm nay là ngày nghỉ hoặc chưa có lịch tập.")
    done = [label for label, completed in sessions if completed]
    if done:
        return Dimension("plan", 100, f"Đã hoàn thành buổi {', '.join(done)}.", {"done": done})
    labels = [label for label, _ in sessions]
    return Dimension("plan", 0, f"Chưa ghi nhận buổi {', '.join(labels)} trong lịch.", {"pending": labels})


def review(features: Features, profile: Profile, *, readiness_score: int | None,
           sessions: list[tuple[str, bool]]) -> DayReview:
    """sessions: các buổi (không phải ngày nghỉ) trong lịch hôm nay, kèm đã ghi nhận hay chưa."""
    dimensions = [nutrition(features, profile), activity(features, profile), sleep(features, profile),
                  recovery(readiness_score), plan(sessions)]
    scored = [d for d in dimensions if d.score is not None]
    if len(scored) < MIN_DIMENSIONS:
        return DayReview(features.today, dimensions, None, None)
    total = sum(WEIGHTS[d.id] for d in scored)
    score = round(sum(WEIGHTS[d.id] * d.score for d in scored) / total)
    grade = next(label for limit, label in GRADES if score >= limit)
    return DayReview(features.today, dimensions, score, grade)


# --------------------------------------------------------------------------------------------------
# Tổng hợp các ảnh chụp thực tế đang hoạt động, kể cả hoạt động ngoài lịch.
# --------------------------------------------------------------------------------------------------

async def _daily_totals(session, model, user_id, options, fields):
    lower, upper = options.utc_bounds()
    timestamp = getattr(model, model.TIME_FIELD)
    day = func.timezone(options.timezone, timestamp).cast(Date).label("day")
    columns = [day, func.count().label("count")]
    item_model, parent_key = (MealItem, MealItem.meal_id) if model is Meal else (TrainingItem, TrainingItem.training_id)
    for name in fields:
        column = getattr(model, name)
        item_sum = select(func.sum(getattr(item_model, name))).where(parent_key == model.id).correlate(model).scalar_subquery()
        known = case((model.detail_status == "AGGREGATE_ONLY", column), else_=item_sum)
        columns.extend((func.sum(known).label(name), func.count(column).label(f"{name}_known")))
    rows = (await session.execute(
        select(*columns).where(model.user_id == user_id, model.is_active.is_(True), timestamp >= lower, timestamp < upper).group_by(day)
    )).mappings().all()
    return {row["day"]: row for row in rows}


async def daily_meal_totals(session, user_id, options: DateRangeQuery):
    """Theo từng ngày địa phương: số bữa, tổng dinh dưỡng đã biết và số bữa có từng giá trị.

    Bữa ăn là dữ liệu HercFit sở hữu (đẩy lên Google, không đọc ngược về), nên chỉ đọc bảng meals.
    """
    return await _daily_totals(session, Meal, user_id, options, NUTRIENT_FIELDS)


def _metric(row, field, target):
    count = row.get("count", 0)
    known_count = row.get(f"{field}_known", 0)
    known_total = row.get(field) or Decimal(0)
    return MetricProgress(
        target=target, actual=known_total if known_count == count else None,
        known_total=known_total, missing_count=count - known_count,
    )


async def summarize_plan(session, *, user_id, plan_id, start_date=None, end_date=None) -> PlanProgressRead:
    """So sánh nhật ký với một kế hoạch tường minh trong quá khứ/hiện tại theo múi giờ riêng của nó."""
    plan = await Plan.get_for_user(session, plan_id, user_id=user_id)
    if plan is None:
        raise HTTPException(404, "Plan not found")
    options = DateRangeQuery(
        start_date=start_date or plan.start_date, end_date=end_date or plan.end_date, timezone=plan.timezone,
    )
    if options.start_date < plan.start_date or options.end_date > plan.end_date:
        raise HTTPException(422, "Progress dates must be within the plan")
    days = await _summarize_days(session, user_id, options, plan)
    return PlanProgressRead(
        plan_id=plan.id, timezone=plan.timezone, start_date=options.start_date, end_date=options.end_date, days=days,
    )


async def summarize_user(session, *, user_id, options: DateRangeQuery) -> ProgressRead:
    """Tổng thực tế theo ngày mà không suy ra chỉ tiêu kế hoạch nào."""
    return ProgressRead(
        timezone=options.timezone, start_date=options.start_date, end_date=options.end_date,
        days=await _summarize_days(session, user_id, options),
    )


async def _summarize_days(session, user_id, options, plan=None):
    from domains.health_records import views
    from domains.health_records.services import daily_expenditure
    from domains.training.services import daily_loads

    expenditure = await daily_expenditure(session, user_id, options.start_date, options.end_date, options.timezone)
    meals = await daily_meal_totals(session, user_id, options)
    trainings = await _daily_totals(session, Training, user_id, options, ("energy_kcal",))
    # Calo tập: buổi trên Google (thiết bị, thể thao ghi qua chat) + gym HercFit chưa gắn với phiên đồng hồ.
    exercise = await views.exercise_kcal(session, user_id, options.start_date, options.end_date, options.timezone)
    loads, _missing = await daily_loads(session, user_id, options.start_date, options.end_date, options.timezone)
    days = []
    day = options.start_date
    while day <= options.end_date:
        meal, training = meals.get(day, {}), trainings.get(day, {})
        days.append(DailyProgressRead(
            date=day, meal_count=meal.get("count", 0), training_count=training.get("count", 0),
            calories_in=_metric(meal, "energy_kcal", getattr(plan, "calories_in_kcal", None)),
            exercise_calories=_metric({"energy_kcal": Decimal(str(exercise[day]))} if day in exercise else {},
                                      "energy_kcal", getattr(plan, "exercise_calories_kcal", None)),
            calories_out_target=getattr(plan, "calories_out_kcal", None),
            calories_out_actual=expenditure.get(day),
            training_load=loads.get(day, Decimal(0)),
            **{field: _metric(meal, field, getattr(plan, field, None)) for field in NUTRIENT_FIELDS if field != "energy_kcal"},
        ))
        day += timedelta(days=1)
    return days
