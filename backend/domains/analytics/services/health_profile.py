"""Hồ sơ và tổng quan sức khoẻ suy ra: hàm thuần trên dữ liệu khai báo và đo lường.

Không gì ở đây được lưu. Mỗi giá trị hồ sơ nêu nguồn gốc của nó (người dùng KHAI BÁO,
thiết bị ĐO, NHÀ CUNG CẤP báo, hoặc SUY RA), và
chênh lệch giữa điều người dùng khai báo và điều thiết bị đo được
báo thành xung đột thay vì âm thầm tự giải quyết. Các dòng là đối tượng ORM hoặc
bất kỳ đối tượng nào có cùng thuộc tính (test dùng SimpleNamespace).
"""
from collections import Counter
from datetime import date, datetime, timedelta
from statistics import mean, median, pstdev
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from domains.analytics.services.daily_health.baseline import median as baseline_median
from domains.health_records.schemas.health import (
    ACTIVITY_LABELS,
    ACTIVITY_ORDER,
    BMI_LABELS,
    HRV_DROP_PCT,
    RHR_ELEVATION_BPM,
    WHO_ACTIVE_MINUTES_PER_WEEK,
    WORN_DAY_MIN_STEPS,
    ActivityOverview,
    EnergyOverview,
    HealthOverviewRead,
    HealthProfileRead,
    ProfileValue,
    RecoveryOverview,
    SleepOverview,
    SleepSessionRead,
    activity_level_from_steps,
    classify_bmi,
    recommended_sleep_hours,
)

MIN_WORN_DAYS_FOR_LEVEL = 7
RHR_CONFLICT_BPM = 8


def _f(value: Any) -> float | None:
    return float(value) if value is not None else None


def _avg(values: Iterable[Any], digits: int = 1) -> float | None:
    numbers = [float(v) for v in values if v is not None]
    return round(mean(numbers), digits) if numbers else None


def _measurement(rows, field: str) -> ProfileValue | None:
    row = next((r for r in rows if getattr(r, field) is not None), None)
    if row is None:
        return None
    source = "MEASURED" if getattr(row, "source", "MANUAL") != "MANUAL" else "DECLARED"
    return ProfileValue(value=round(float(getattr(row, field)), 2), source=source, observed_at=row.recorded_at)


def worn_days(daily) -> list:
    return [d for d in daily if d.steps is not None and d.steps >= WORN_DAY_MIN_STEPS]


def build_profile(*, today: date, zone: str, user, metrics, daily, connection=None) -> HealthProfileRead:
    """metrics: body_metrics mới nhất trước; daily: tổng hợp ngày của 28 ngày gần nhất."""
    personal = user.personal_info or {}
    training = personal.get("training") or {}
    provider = (connection.provider_profile if connection is not None else None) or {}
    profile = HealthProfileRead(as_of=today, timezone=zone,
                                connected=connection is not None and connection.status in {"ACTIVE", "NEEDS_REAUTH"})
    if user.age is not None:
        profile.age = ProfileValue(value=user.age, source="DECLARED")
    elif provider.get("age") is not None:
        profile.age = ProfileValue(value=int(provider["age"]), source="PROVIDER")
    if user.sex:
        profile.sex = ProfileValue(value=user.sex, source="DECLARED")
    profile.height_cm = _measurement(metrics, "height_cm")
    profile.weight_kg = _measurement(metrics, "weight_kg")
    profile.body_fat_pct = _measurement(metrics, "body_fat_pct")
    if profile.height_cm and profile.weight_kg:
        bmi = round(float(profile.weight_kg.value) / (float(profile.height_cm.value) / 100) ** 2, 1)
        category = classify_bmi(bmi)
        profile.bmi = ProfileValue(value=bmi, source="DERIVED", observed_at=profile.weight_kg.observed_at,
                                   label=f"{category} ({BMI_LABELS[category]}, ngưỡng châu Á)")

    week = [d for d in daily if d.local_date > today - timedelta(days=7)]
    resting = [d.resting_hr_bpm for d in week if d.resting_hr_bpm is not None]
    declared_rhr = training.get("resting_hr")
    if resting:
        profile.resting_hr_bpm = ProfileValue(value=round(median(resting)), source="MEASURED",
                                              observed_at=max(d.local_date for d in week if d.resting_hr_bpm is not None),
                                              label="trung vị 7 ngày")
        if isinstance(declared_rhr, (int, float)) and abs(declared_rhr - profile.resting_hr_bpm.value) >= RHR_CONFLICT_BPM:
            profile.conflicts.append(f"Nhịp tim nghỉ khai báo {declared_rhr} bpm nhưng thiết bị đo trung vị "
                                     f"{profile.resting_hr_bpm.value} bpm trong 7 ngày qua")
    elif isinstance(declared_rhr, (int, float)):
        profile.resting_hr_bpm = ProfileValue(value=declared_rhr, source="DECLARED")
    if isinstance(training.get("max_hr"), (int, float)):
        profile.max_hr_bpm = ProfileValue(value=training["max_hr"], source="DECLARED")
    elif profile.age is not None:
        profile.max_hr_bpm = ProfileValue(value=round(208 - 0.7 * float(profile.age.value)), source="DERIVED",
                                          label="công thức Tanaka 208 − 0,7 × tuổi")
    hrv = _avg((d.hrv_ms for d in week), 1)
    if hrv is not None:
        profile.hrv_ms = ProfileValue(value=hrv, source="MEASURED", label="trung bình 7 ngày")
    vo2 = next((d for d in sorted(daily, key=lambda d: d.local_date, reverse=True) if d.vo2_max is not None), None)
    if vo2 is not None:
        profile.vo2_max = ProfileValue(value=float(vo2.vo2_max), source="MEASURED", observed_at=vo2.local_date)

    worn = worn_days(daily)
    profile.worn_days_28d = len(worn)
    profile.steps_avg_28d = _avg((d.steps for d in worn), 0)
    profile.steps_avg_7d = _avg((d.steps for d in worn if d.local_date > today - timedelta(days=7)), 0)
    minutes = [d.active_minutes for d in week if d.active_minutes is not None]
    profile.active_minutes_7d = sum(minutes) if minutes else None
    profile.sleep_avg_minutes_7d = _avg((d.sleep_minutes for d in week), 0)

    declared_level = ((personal.get("activity") or {}).get("level"))
    if declared_level:
        profile.activity_level = ProfileValue(value=declared_level, source="DECLARED",
                                              label=ACTIVITY_LABELS.get(declared_level))
    observed = activity_level_from_steps(profile.steps_avg_28d) if len(worn) >= MIN_WORN_DAYS_FOR_LEVEL else None
    if observed:
        profile.observed_activity_level = ProfileValue(
            value=observed, source="DERIVED", label=f"{ACTIVITY_LABELS[observed]}, TB {int(profile.steps_avg_28d):,} bước/ngày "
                                                    f"({len(worn)} ngày có đeo thiết bị)".replace(",", "."))
        if declared_level in ACTIVITY_ORDER and abs(ACTIVITY_ORDER.index(declared_level) - ACTIVITY_ORDER.index(observed)) >= 2:
            profile.conflicts.append(
                f"Mức vận động khai báo '{ACTIVITY_LABELS[declared_level]}' nhưng 28 ngày qua TB "
                f"{int(profile.steps_avg_28d):,} bước/ngày ({ACTIVITY_LABELS[observed]})".replace(",", "."))
    for field in ("age", "sex", "height_cm", "weight_kg"):
        if getattr(profile, field) is None:
            profile.missing_fields.append(field)
    if profile.activity_level is None and profile.observed_activity_level is None:
        profile.missing_fields.append("activity_level")
    return profile


def effective_activity_level(profile: HealthProfileRead) -> str | None:
    """Ưu tiên mức đã khai báo; mức thiết bị quan sát được điền vào khi chưa khai báo."""
    for value in (profile.activity_level, profile.observed_activity_level):
        if value is not None and value.value in ACTIVITY_ORDER:
            return str(value.value)
    return None


# ---------------------------------------------------------------------------
# Tổng quan
# ---------------------------------------------------------------------------
def _activity(daily, workouts, end: date) -> ActivityOverview:
    worn = worn_days(daily)
    recent = [d for d in worn if d.local_date > end - timedelta(days=7)]
    earlier = [d for d in worn if d.local_date <= end - timedelta(days=7)]
    steps_7d, steps_prev = _avg((d.steps for d in recent), 0), _avg((d.steps for d in earlier), 0)
    week = [d for d in daily if d.local_date > end - timedelta(days=7)]
    active_week = [d.active_minutes for d in week if d.active_minutes is not None]
    azm_week = [d.active_zone_minutes for d in week if d.active_zone_minutes is not None]
    distance = _avg((float(d.distance_m) / 1000 for d in worn if d.distance_m is not None), 2)
    level = activity_level_from_steps(_avg(d.steps for d in worn)) if len(worn) >= MIN_WORN_DAYS_FOR_LEVEL else None
    return ActivityOverview(
        days_with_data=len(worn), steps_avg=_avg((d.steps for d in worn), 0), steps_avg_7d=steps_7d,
        steps_trend_pct=round(100 * (steps_7d - steps_prev) / steps_prev, 1) if steps_7d and steps_prev else None,
        distance_km_avg=distance,
        active_minutes_week=float(sum(active_week)) if active_week else None,
        meets_who_guideline=sum(active_week) >= WHO_ACTIVE_MINUTES_PER_WEEK if active_week else None,
        active_zone_minutes_week=float(sum(azm_week)) if azm_week else None,
        total_kcal_avg=_avg((d.total_kcal for d in worn), 0), active_kcal_avg=_avg((d.active_kcal for d in worn), 0),
        observed_level=level, workouts=len(workouts),
        workout_minutes=round(sum((w.active_seconds or 0) for w in workouts) / 60, 1),
        workout_types=dict(Counter((w.exercise_type or "OTHER") for w in workouts)),
    )


def _bedtime_minutes(session, zone: ZoneInfo) -> float:
    local = session.start_at.astimezone(zone)
    minutes = local.hour * 60 + local.minute
    return minutes + 1440 if minutes < 12 * 60 else minutes  # 01:00 được xếp sau 23:00


def _sleep(sessions, end: date, age: int | None, zone: str) -> SleepOverview:
    main = sorted((s for s in sessions if not s.is_nap), key=lambda s: s.end_at)
    low, high = recommended_sleep_hours(age)
    staged = [s for s in main if s.deep_minutes is not None and s.rem_minutes is not None]
    staged_total = sum((s.deep_minutes or 0) + (s.light_minutes or 0) + (s.rem_minutes or 0) for s in staged)
    bedtimes = [_bedtime_minutes(s, ZoneInfo(zone)) for s in main]
    last = main[-1] if main else None
    return SleepOverview(
        nights=len(main), avg_minutes=_avg((s.minutes_asleep for s in main), 0),
        avg_minutes_7d=_avg((s.minutes_asleep for s in main if s.local_date > end - timedelta(days=7)), 0),
        recommended_hours=(low, high),
        nights_below_recommended=sum(1 for s in main if s.minutes_asleep is not None and s.minutes_asleep < low * 60),
        deep_pct=round(100 * sum(s.deep_minutes for s in staged) / staged_total, 1) if staged_total else None,
        rem_pct=round(100 * sum(s.rem_minutes for s in staged) / staged_total, 1) if staged_total else None,
        efficiency_pct=_avg((s.efficiency_pct for s in main), 1),
        bedtime_stdev_minutes=round(pstdev(bedtimes), 0) if len(bedtimes) >= 3 else None,
        last_night=SleepSessionRead.model_validate(last) if last is not None else None,
    )


def _recovery(daily, end: date) -> RecoveryOverview:
    """Trung vị 7 ngày gần nhất so với trung vị các ngày trước đó trong cửa sổ (đường nền dùng chung)."""
    recent = [d for d in daily if d.local_date > end - timedelta(days=7)]
    baseline = [d for d in daily if d.local_date <= end - timedelta(days=7)]
    rhr_7d, rhr_base = baseline_median(d.resting_hr_bpm for d in recent), baseline_median(d.resting_hr_bpm for d in baseline)
    hrv_7d, hrv_base = baseline_median(d.hrv_ms for d in recent), baseline_median(d.hrv_ms for d in baseline)
    enough_rhr = sum(1 for d in baseline if d.resting_hr_bpm is not None) >= 7
    enough_hrv = sum(1 for d in baseline if d.hrv_ms is not None) >= 7
    elevated = rhr_7d - rhr_base >= RHR_ELEVATION_BPM if rhr_7d is not None and rhr_base is not None and enough_rhr else None
    suppressed = (100 * (hrv_base - hrv_7d) / hrv_base >= HRV_DROP_PCT
                  if hrv_7d is not None and hrv_base and enough_hrv else None)
    signals = []
    if elevated:
        signals.append(f"Nhịp tim nghỉ 7 ngày ({rhr_7d} bpm) cao hơn nền trước đó ({rhr_base} bpm) "
                       f"≥ {RHR_ELEVATION_BPM} bpm: có thể cơ thể chưa hồi phục đủ")
    if suppressed:
        signals.append(f"HRV 7 ngày ({hrv_7d} ms) thấp hơn nền ({hrv_base} ms) ≥ {HRV_DROP_PCT}%")
    return RecoveryOverview(
        resting_hr_7d=rhr_7d, resting_hr_baseline=rhr_base if enough_rhr else None, resting_hr_elevated=elevated,
        hrv_7d=hrv_7d, hrv_baseline=hrv_base if enough_hrv else None, hrv_suppressed=suppressed,
        spo2_avg=_avg((d.spo2_avg_pct for d in recent), 1), respiratory_rate_avg=_avg((d.respiratory_rate for d in recent), 1),
        signals=signals,
    )


def _energy(out: dict[date, float], intake: dict[date, float], weights: list[tuple[date, float]],
            end: date) -> EnergyOverview:
    """out: tổng năng lượng tiêu hao theo ngày (views.energy_out: total-calories của Google cộng buổi ghi tay)."""
    paired = [(day, intake[day], kcal) for day, kcal in sorted(out.items()) if day in intake and day < end]
    change = round(weights[-1][1] - weights[0][1], 2) if len(weights) >= 2 else None
    intake_avg = _avg((p[1] for p in paired), 0)
    out_avg = _avg((p[2] for p in paired), 0)
    note = None
    if paired:
        note = ("Calo tiêu hao từ thiết bị là ước tính (sai số có thể 10–25%); đối chiếu với xu hướng cân nặng "
                "trước khi kết luận về thâm hụt hay dư thừa.")
    return EnergyOverview(complete_days=len(paired), intake_kcal_avg=intake_avg, device_expenditure_kcal_avg=out_avg,
                          balance_kcal_avg=round(intake_avg - out_avg) if paired else None,
                          weight_change_kg=change, note=note)


def build_overview(*, start: date, end: date, zone: str, connected: bool, age: int | None, daily, sleep, workouts,
                   intake: dict[date, float], weights: list[tuple[date, float]],
                   energy_out: dict[date, float] | None = None) -> HealthOverviewRead:
    """intake: năng lượng bữa ăn của các ngày trọn theo ngày; weights: (ngày, kg) cũ nhất trước."""
    notes = []
    if not connected:
        notes.append("Chưa kết nối Google Health: vào Cài đặt → Kết nối để đồng bộ dữ liệu từ thiết bị.")
    worn = len(worn_days(daily))
    span = (end - start).days + 1
    if connected and worn < span / 2:
        notes.append(f"Chỉ {worn}/{span} ngày có dữ liệu bước chân; kết luận về vận động có thể chưa đại diện.")
    return HealthOverviewRead(
        start_date=start, end_date=end, timezone=zone, connected=connected,
        activity=_activity(daily, workouts, end), sleep=_sleep(sleep, end, age, zone),
        recovery=_recovery(daily, end), notes=notes,
        energy=_energy(energy_out if energy_out is not None else
                       {d.local_date: float(d.total_kcal) for d in daily if d.total_kcal is not None},
                       intake, weights, end),
    )


def to_local_date(moment: datetime, zone: str) -> date:
    return moment.astimezone(ZoneInfo(zone)).date()
