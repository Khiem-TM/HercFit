"""Context API của trợ lý: các con số tính sẵn, có nguồn, trong một ngân sách token.

Mỗi mục là {key, label, value, unit, source, measured_at, freshness_s, coverage,
method, algorithm_version, evidence}. Trợ lý đọc các con số này; nó không bao giờ
tính lại tổng, đường nền hay chỉ số từ hàng nghìn mẫu.

Các luật áp dụng cho mọi chủ đề:
* mục đo bởi thiết bị cần consent `device` của bên đọc; mục nhạy cảm
  (đường huyết, phân loại ECG/IRN, nhật ký triệu chứng/tâm trạng/sinh sản) cần
  consent `sensitive` riêng; kiểm tra trực tiếp ở mỗi lần dựng.
* dạng sóng ECG, lộ trình GPS và token không bao giờ thuộc một ngữ cảnh.
* dữ liệu thiếu được nêu rõ (trạng thái độ phủ), không bao giờ là số 0 hay phỏng đoán.
* ảnh chụp được lưu theo (chủ đề, khoảng thời gian) cùng phiên bản consent lúc
  dựng; thay đổi consent sẽ xoá chúng và phiên bản khác không bao giờ được phục vụ.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from domains.analytics.services import coverage as coverage_service
from domains.body.models.body_metrics import BodyMetric
from domains.health_records.models.clinical import EcgRecording, IrnAlert
from domains.health_records.models.device_records import DeviceWorkout, HealthSample, SleepSession
from domains.health_records.schemas.health import HEALTH_PROVIDER, HealthOverviewQuery
from domains.identity import consent
from domains.nutrition.models.logs import HydrationLog
from domains.wellbeing.models.logs import MoodLog, SymptomLog

TOPICS = ("overview", "activity", "sleep", "recovery", "body", "nutrition", "vitals", "wellbeing")
SENSITIVE_TOPICS = {"vitals", "wellbeing"}
PERIODS = {"7d": 7, "28d": 28, "90d": 90}
BASE_BUDGET = 1500
DEEP_BUDGET = 4000
SNAPSHOT_TTL = timedelta(minutes=15)
METHOD_VERSION = "context-v1"


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
                              evidence=[{"table": "body_metrics", "id": str(latest.id)}], now=now))
        height = next((m for m in metrics if m.height_cm is not None), None)
        if height is not None:
            items.append(item("body.height", "Chiều cao", _round(height.height_cm, 1), "cm", source=height.source,
                              measured_at=height.recorded_at, method="latest measurement",
                              evidence=[{"table": "body_metrics", "id": str(height.id)}], now=now))
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
                item("activity.device_workouts", "Buổi tập thiết bị ghi", a.workouts, "sessions", source=HEALTH_PROVIDER,
                     measured_at=end, method=f"count in {days}d (device sessions; no sets/reps)", now=now),
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
                nights = (await session.execute(select(SleepSession).where(
                    SleepSession.user_id == user.id, SleepSession.is_active.is_(True), SleepSession.is_nap.is_(False),
                    SleepSession.local_date >= start).order_by(SleepSession.local_date.desc()).limit(14))).scalars()
                for night in nights:
                    items.append(item(f"sleep.night.{night.local_date}", "Đêm", {
                        "asleep": night.minutes_asleep, "deep": night.deep_minutes, "rem": night.rem_minutes,
                        "awake": night.awake_minutes, "efficiency": _round(night.efficiency_pct)}, "min",
                        source=HEALTH_PROVIDER, measured_at=night.end_at, method="provider sleep summary",
                        evidence=[{"table": "sleep_sessions", "id": str(night.id)}], now=now))
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
                              method="logged intake on complete days vs device total energy (workout kcal not added again)",
                              now=now))
        if topic == "nutrition":
            water = (await session.execute(text("""
                SELECT source, round(sum(amount_ml)) AS ml, count(*) AS n FROM hydration_logs
                WHERE user_id = :u AND is_active AND local_date >= :start GROUP BY source"""),
                {"u": user.id, "start": start})).mappings().all()
            for row in water:  # theo từng nguồn: không bao giờ cộng gộp giữa các nguồn
                items.append(item(f"hydration.{row['source'].lower()}", "Nước uống ghi nhận", float(row["ml"]), "ml",
                                  source=row["source"], measured_at=end, method=f"sum of {row['n']} logs in {days}d",
                                  now=now))
    elif not device and topic != "body":
        withheld.append("device_data")

    if topic == "vitals":
        glucose = (await session.execute(select(HealthSample).where(
            HealthSample.user_id == user.id, HealthSample.is_active.is_(True),
            HealthSample.sample_type == "BLOOD_GLUCOSE").order_by(HealthSample.measured_at.desc()).limit(10))).scalars()
        for sample in glucose:
            items.append(item(f"vitals.glucose.{sample.id}", "Đường huyết", _round(sample.value, 1), sample.unit,
                              source=sample.source, measured_at=sample.measured_at, method="provider measurement",
                              evidence=[{"table": "health_samples", "id": str(sample.id)}], now=now))
        for ecg in (await session.execute(select(EcgRecording).where(
                EcgRecording.user_id == user.id, EcgRecording.is_active.is_(True)).order_by(
                EcgRecording.started_at.desc()).limit(5))).scalars():
            items.append(item(f"vitals.ecg.{ecg.id}", "ECG (kết luận của thiết bị)", ecg.classification, None,
                              source=ecg.source, measured_at=ecg.started_at,
                              method="provider classification, reported as-is (no diagnosis)",
                              evidence=[{"table": "ecg_recordings", "id": str(ecg.id)}], now=now))
        for alert in (await session.execute(select(IrnAlert).where(
                IrnAlert.user_id == user.id, IrnAlert.is_active.is_(True)).order_by(
                IrnAlert.started_at.desc()).limit(5))).scalars():
            items.append(item(f"vitals.irn.{alert.id}", "Cảnh báo nhịp bất thường", alert.positive_windows, "windows",
                              source=alert.source, measured_at=alert.started_at, method="provider notification",
                              evidence=[{"table": "irn_alerts", "id": str(alert.id)}], now=now))
    if topic == "overview" and sensitive:
        from core.flags import reader_v2

        if reader_v2("wellbeing"):
            summary = (await session.execute(text("""
                SELECT (SELECT count(*) FROM mood_logs WHERE user_id = :u AND is_active AND local_date >= :start) AS moods,
                       (SELECT count(*) FROM mood_logs WHERE user_id = :u AND is_active AND local_date >= :start
                          AND valences @> '["UNPLEASANT"]'::jsonb) AS unpleasant,
                       (SELECT count(DISTINCT local_date) FROM symptom_logs WHERE user_id = :u AND is_active
                          AND local_date >= :start) AS symptom_days"""), {"u": user.id, "start": start})).one()
            if summary.moods or summary.symptom_days:
                items.append(item("wellbeing.summary", "Nhật ký tâm trạng và triệu chứng (chỉ số đếm)",
                                  {"mood_logs": summary.moods, "unpleasant_mood_logs": summary.unpleasant,
                                   "days_with_symptoms": summary.symptom_days}, "count", source="USER_LOGS",
                                  measured_at=end, method=f"counts in {days}d; details only on topic=wellbeing",
                                  now=now))
    if topic == "wellbeing":
        for log in (await session.execute(select(SymptomLog).where(
                SymptomLog.user_id == user.id, SymptomLog.is_active.is_(True), SymptomLog.local_date >= start).order_by(
                SymptomLog.recorded_at.desc()).limit(20))).scalars():
            items.append(item(f"wellbeing.symptoms.{log.id}", "Triệu chứng", log.symptoms, None, source=log.source,
                              measured_at=log.recorded_at, method="user log",
                              evidence=[{"table": "symptom_logs", "id": str(log.id)}], now=now))
        for log in (await session.execute(select(MoodLog).where(
                MoodLog.user_id == user.id, MoodLog.is_active.is_(True), MoodLog.local_date >= start).order_by(
                MoodLog.recorded_at.desc()).limit(20))).scalars():
            items.append(item(f"wellbeing.mood.{log.id}", "Tâm trạng", {"moods": log.moods, "valences": log.valences},
                              None, source=log.source, measured_at=log.recorded_at, method="user log",
                              evidence=[{"table": "mood_logs", "id": str(log.id)}], now=now))
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
    """Phục vụ ảnh chụp mới dựng theo phiên bản consent hiện tại, nếu không thì dựng lại và lưu."""
    decision = await consent.load(session, user.id)
    device = await consent.device_access(session, user.id)
    scope = "device" if device else "own"
    row = (await session.execute(text("""
        SELECT payload, generated_at FROM context_snapshots
        WHERE user_id = :u AND topic = :topic AND period = :period AND consent_version = :version"""),
        {"u": user.id, "topic": f"{topic}:{scope}", "period": period, "version": decision.version})).first()
    if row is not None and datetime.now(timezone.utc) - row.generated_at < SNAPSHOT_TTL:
        return fit(row.payload, budget)
    context = await build(session, user, topic=topic, period=period, zone=zone)
    await session.execute(text("""
        INSERT INTO context_snapshots (user_id, topic, period, consent_version, payload, tokens, generated_at)
        VALUES (:u, :topic, :period, :version, CAST(:payload AS jsonb), :tokens, now())
        ON CONFLICT (user_id, topic, period) DO UPDATE SET consent_version = EXCLUDED.consent_version,
            payload = EXCLUDED.payload, tokens = EXCLUDED.tokens, generated_at = now()"""),
        {"u": user.id, "topic": f"{topic}:{scope}", "period": period, "version": decision.version,
         "payload": json.dumps(context, ensure_ascii=False, default=str), "tokens": tokens(context)})
    return fit(json.loads(json.dumps(context, default=str)), budget)


async def purge_snapshots(session, user_id: UUID) -> int:
    return (await session.execute(text("DELETE FROM context_snapshots WHERE user_id = :u"), {"u": user_id})).rowcount or 0
