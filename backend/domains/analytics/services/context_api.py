"""Context API của trợ lý: các con số tính sẵn, có nguồn, trong một ngân sách token.

Mỗi mục là {key, label, value, unit, source, measured_at, freshness_s, coverage,
method, algorithm_version, evidence}. Trợ lý đọc các con số này; nó không bao giờ
tính lại tổng, đường nền hay chỉ số từ hàng nghìn mẫu.

Các luật áp dụng cho mọi chủ đề:
* mục đo bởi thiết bị cần consent `device` của bên đọc; mục nhạy cảm
  (đường huyết, phân loại ECG/IRN) cần consent `sensitive` riêng; kiểm tra ở mỗi lần dựng.
* dạng sóng ECG, lộ trình GPS và token không bao giờ thuộc một ngữ cảnh.
* dữ liệu thiếu được nêu rõ (trạng thái độ phủ), không bao giờ là số 0 hay phỏng đoán.
* ngữ cảnh được dựng mỗi lần đọc từ health_points (nhanh, không có bảng cache), nên luôn
  khớp quyết định consent hiện tại.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from domains.analytics.services import coverage as coverage_service
from domains.body.models.body_metrics import BodyMetric
from domains.health_records import views
from domains.health_records.schemas.health import HEALTH_PROVIDER, HealthOverviewQuery
from domains.identity import consent

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
         now: datetime | None = None, algorithm_version: str = METHOD_VERSION) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    stamp = measured_at
    freshness = None
    if isinstance(measured_at, datetime):
        freshness = int((now - measured_at).total_seconds())
        stamp = measured_at.isoformat()
    elif isinstance(measured_at, date):
        freshness = (now.date() - measured_at).days * 86400
        stamp = measured_at.isoformat()
    return {"key": key, "label": label, "value": value, "unit": unit, "source": source, "measured_at": stamp,
            "freshness_s": freshness, "coverage": coverage, "method": method, "algorithm_version": algorithm_version,
            "evidence": evidence or []}


def _round(value: Any, digits: int = 1) -> Any:
    return round(float(value), digits) if value is not None else None


def _coverage(report: dict[str, Any], column: str) -> dict[str, Any]:
    entry = report.get(column) or {}
    return {"state": entry.get("state", "NO_DATA"), "observed_days": entry.get("observed_days", 0),
            "days": entry.get("days", 0)}


async def _overview(session, user, period_days: int, zone: str):
    from domains.health_records.services.health_service import HealthService

    service = HealthService(session, user)
    return await service.overview(HealthOverviewQuery(days=period_days, timezone=zone))


async def build(session, user, *, topic: str, period: str, zone: str, now: datetime | None = None) -> dict[str, Any]:
    if topic not in TOPICS or period not in PERIODS:
        raise ValueError("unknown topic or period")
    now = now or datetime.now(timezone.utc)
    days = PERIODS[period]
    decision = await consent.load(session, user.id)
    device = await consent.device_access(session, user.id)
    sensitive = await consent.device_access(session, user.id, "sensitive")
    end = now.date()
    start = end - timedelta(days=days - 1)
    items: list[dict[str, Any]] = []
    withheld: list[str] = []
    if topic in SENSITIVE_TOPICS and not sensitive:
        return {"topic": topic, "period": period, "items": [], "withheld": [topic], "consent_version": decision.version}
    report = await coverage_service.coverage(session, user.id, start, end) if device else {}

    if topic in ("overview", "body"):
        metrics = await BodyMetric.list_for_user(session, user_id=user.id, limit=20)
        latest = next((m for m in metrics if m.weight_kg is not None), None)
        if latest is not None:
            items.append(item("body.weight", "Cân nặng gần nhất", _round(latest.weight_kg, 2), "kg",
                              source=latest.source, measured_at=latest.recorded_at, method="latest weigh-in",
                              evidence=[{"id": str(latest.id)}], now=now))
        height = next((m for m in metrics if m.height_cm is not None), None)
        if height is not None:
            items.append(item("body.height", "Chiều cao", _round(height.height_cm, 1), "cm", source=height.source,
                              measured_at=height.recorded_at, method="latest measurement",
                              evidence=[{"id": str(height.id)}], now=now))
        if not device:
            withheld.append("device_body_metrics")
    if device and topic in ("overview", "activity", "sleep", "recovery", "nutrition"):
        overview = await _overview(session, user, days, zone)
        a, s, r, e = overview.activity, overview.sleep, overview.recovery, overview.energy
        if topic in ("overview", "activity"):
            items += [
                item("activity.steps_avg", "Bước chân trung bình/ngày", _round(a.steps_avg, 0), "steps",
                     source=HEALTH_PROVIDER, measured_at=end, coverage=_coverage(report, "steps"),
                     method=f"mean of observed days in {days}d", now=now),
                item("activity.active_minutes_week", "Phút vận động vừa–mạnh/tuần", _round(a.active_minutes_week, 0),
                     "min", source=HEALTH_PROVIDER, measured_at=end, coverage=_coverage(report, "active_minutes"),
                     method="moderate+vigorous minutes, weekly rate; WHO target 150", now=now),
                item("activity.device_workouts", "Buổi tập thể thao trên Google Health", a.workouts, "sessions",
                     source=HEALTH_PROVIDER, measured_at=end,
                     method=f"count in {days}d (watch, chat-logged sport and other apps; gym logs are separate)",
                     now=now),
            ]
        if topic in ("overview", "sleep"):
            items += [
                item("sleep.avg_minutes", "Ngủ trung bình/đêm", _round(s.avg_minutes, 0), "min", source=HEALTH_PROVIDER,
                     measured_at=end, coverage=_coverage(report, "sleep_minutes"),
                     method="mean minutes asleep of main sleeps (naps excluded)", now=now),
                item("sleep.efficiency", "Hiệu quả giấc ngủ", _round(s.efficiency_pct, 1), "%", source=HEALTH_PROVIDER,
                     measured_at=end, method="asleep / in-bed of main sleeps", now=now),
            ]
            if topic == "sleep":
                nights = sorted((night for night in await views.sleep(session, user.id, start, end) if not night.is_nap),
                                key=lambda night: night.local_date, reverse=True)[:14]
                for night in nights:
                    items.append(item(f"sleep.night.{night.local_date}", "Đêm", {
                        "asleep": night.minutes_asleep, "deep": night.deep_minutes, "rem": night.rem_minutes,
                        "awake": night.awake_minutes, "efficiency": _round(night.efficiency_pct)}, "min",
                        source=HEALTH_PROVIDER, measured_at=night.end_at, method="provider sleep summary",
                        evidence=[{"id": str(night.id)}], now=now))
        if topic in ("overview", "recovery"):
            items += [
                item("recovery.resting_hr", "Nhịp tim nghỉ 7 ngày vs nền 28 ngày",
                     {"recent": _round(r.resting_hr_7d), "baseline": _round(r.resting_hr_baseline),
                      "elevated": r.resting_hr_elevated}, "bpm", source=HEALTH_PROVIDER, measured_at=end,
                     coverage=_coverage(report, "resting_hr_bpm"), method="median; elevated if ≥5 bpm above baseline",
                     now=now, algorithm_version=coverage_service.ALGORITHM_VERSION),
                item("recovery.hrv", "HRV 7 ngày vs nền 28 ngày",
                     {"recent": _round(r.hrv_7d), "baseline": _round(r.hrv_baseline), "suppressed": r.hrv_suppressed},
                     "ms", source=HEALTH_PROVIDER, measured_at=end, coverage=_coverage(report, "hrv_ms"),
                     method="median; suppressed if ≥15% below baseline", now=now,
                     algorithm_version=coverage_service.ALGORITHM_VERSION),
            ]
        if topic in ("overview", "nutrition"):
            items.append(item("energy.balance", "Cân bằng năng lượng (ngày ghi đủ)",
                              {"intake": _round(e.intake_kcal_avg, 0), "device_out": _round(e.device_expenditure_kcal_avg, 0),
                               "balance": _round(e.balance_kcal_avg, 0), "complete_days": e.complete_days}, "kcal",
                              source="DERIVED", measured_at=end,
                              method="logged intake on complete days vs total energy out (Google total-calories "
                                     "+ manually logged sessions, which Google does not add)",
                              now=now))
        if topic == "nutrition":
            water = [row.hydration_ml for row in await views.daily(session, user.id, start, end, zone)
                     if row.hydration_ml is not None]
            if water:
                items.append(item("hydration.total", "Nước uống ghi nhận", _round(sum(water), 0), "ml",
                                  source=HEALTH_PROVIDER, measured_at=end, coverage=_coverage(report, "hydration_ml"),
                                  method=f"sum of hydration logs on {len(water)} days in {days}d", now=now))
    elif not device and topic != "body":
        withheld.append("device_data")

    if topic == "vitals":
        for sample in sorted(await views.samples(session, user.id, start, end, "BLOOD_GLUCOSE"),
                             key=lambda sample: sample.measured_at, reverse=True)[:10]:
            items.append(item(f"vitals.glucose.{sample.id}", "Đường huyết", _round(sample.value, 1), sample.unit,
                              source=sample.source, measured_at=sample.measured_at, method="provider measurement",
                              evidence=[{"id": str(sample.id)}], now=now))
        for ecg in (await views.sessions(session, user.id, "electrocardiogram", start, end))[-5:]:
            items.append(item(f"vitals.ecg.{ecg['id']}", "ECG (kết luận của thiết bị)", ecg.get("resultClassification"),
                              None, source=HEALTH_PROVIDER, measured_at=ecg["started_at"],
                              method="provider classification, reported as-is (no diagnosis)",
                              evidence=[{"id": str(ecg["id"])}], now=now))
        for alert in (await views.sessions(session, user.id, "irregular-rhythm-notification", start, end))[-5:]:
            positive = sum(1 for window in alert.get("alertWindows") or [] if (window or {}).get("positive"))
            items.append(item(f"vitals.irn.{alert['id']}", "Cảnh báo nhịp bất thường", positive, "windows",
                              source=HEALTH_PROVIDER, measured_at=alert["started_at"], method="provider notification",
                              evidence=[{"id": str(alert["id"])}], now=now))
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


async def get(session, user, *, topic: str = "overview", period: str = "28d", budget: int = BASE_BUDGET,
              zone: str = "Asia/Ho_Chi_Minh") -> dict[str, Any]:
    """Ngữ cảnh dựng theo quyết định consent hiện tại, cắt theo ngân sách token."""
    context = await build(session, user, topic=topic, period=period, zone=zone)
    return fit(json.loads(json.dumps(context, default=str)), budget)
