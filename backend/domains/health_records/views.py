"""Đọc `health_points` thành những gì HercFit dùng: ngày, phiên ngủ, buổi tập, mẫu rời và calo.

Ánh xạ trường Google → chỉ số HercFit nằm ở đây, một chỗ duy nhất. Logic được chuyển nguyên từ
projections.py cũ và giữ các điểm đã kiểm chứng: AZM = tổng sumIn*HeartZone; phút vận động chỉ
tính mức vừa trở lên; nhiệt độ da = đêm − nền; một đêm thuộc ngày thức dậy. Kết quả dùng đúng
schema đọc hiện có (DailyHealthRead, SleepSessionRead, DeviceWorkoutRead, HealthSampleRead), nên
API, phân tích và knowledge graph giữ nguyên tên trường.

Calo (mỗi buổi tập chỉ đếm một lần):
* `exercise_kcal(day)` = kcal mọi buổi tập trong health_points + kcal buổi gym local chưa gắn với
  phiên đồng hồ (gym HercFit đã đẩy lên bị loại khỏi health_points khi đọc).
* `energy_out(day)` = total-calories của Google + kcal buổi tập do HercFit ghi (Google không cộng
  phiên ghi tay vào rollup) + kcal buổi gym local chưa gắn với phiên đồng hồ.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID, uuid5

from sqlalchemy import select, text

from domains.health_records.models.health_points import HealthPoint
from domains.health_records.types import number
from domains.health_records.schemas.health import (
    HEALTH_PROVIDER, DailyHealthRead, DeviceWorkoutRead, HealthSampleRead, SleepSessionRead,
)
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE

NAMESPACE = UUID("6f1d2c7e-3a7b-4f53-9f0e-2c4d6b8a9e10")
# Khoảng hợp lý của từng chỉ số theo ngày; giá trị ngoài khoảng coi như không có.
RANGES = {
    "steps": (0, 1_000_000), "distance_m": (0, 1_000_000), "floors": (0, 10_000), "active_minutes": (0, 1440),
    "active_zone_minutes": (0, 2880), "total_kcal": (0, 50_000), "active_kcal": (0, 50_000),
    "resting_hr_bpm": (20, 250), "hr_avg_bpm": (20, 300), "hr_min_bpm": (20, 300), "hr_max_bpm": (20, 300),
    "hrv_ms": (0, 1000), "spo2_avg_pct": (0, 100), "respiratory_rate": (0, 100), "vo2_max": (0, 100),
    "hydration_ml": (0, 100_000), "sleep_minutes": (0, 1440), "skin_temp_delta_c": (-20, 20),
    "sedentary_minutes": (0, 1440),
}
LIGHT_LEVELS = {"SEDENTARY", "LIGHTLY_ACTIVE", "LIGHT", "ACTIVITY_LEVEL_UNSPECIFIED"}
DAILY_TYPES = ("steps", "distance", "floors", "active-minutes", "active-zone-minutes", "active-energy-burned",
               "total-calories", "heart-rate", "daily-resting-heart-rate", "daily-heart-rate-variability",
               "daily-oxygen-saturation", "daily-respiratory-rate", "daily-vo2-max",
               "daily-sleep-temperature-derivations", "hydration-log", "sleep", "sedentary-period")
# Mẫu rời: loại → (sample_type, đường dẫn giá trị, đơn vị, các trường chi tiết)
SAMPLES = {
    "blood-glucose": ("BLOOD_GLUCOSE", "bloodGlucoseMilligramsPerDeciliter", "mg/dL",
                      ("mealType", "measurementTiming", "specimen", "measurementSource")),
    "core-body-temperature": ("CORE_BODY_TEMPERATURE", "temperatureCelsius", "C", ("measurementLocation",)),
    "vo2-max": ("VO2_MAX", "vo2Max", "mL/kg/min", ("measurementMethod",)),
    "run-vo2-max": ("RUN_VO2_MAX", "runVo2Max", "mL/kg/min", ()),
    "respiratory-rate-sleep-summary": ("SLEEP_RESPIRATORY_RATE", "fullSleepStats.breathsPerMinute", "breaths/min", ()),
}
SAMPLE_TYPES = {sample_type: data_type for data_type, (sample_type, *_rest) in SAMPLES.items()}
# Số đo cơ thể: loại → (cột HercFit, trường Google, hệ số, số chữ số)
BODY = {"weight": ("weight_kg", "weightGrams", 0.001, 3), "height": ("height_cm", "heightMillimeters", 0.1, 1),
        "body-fat": ("body_fat_pct", "percentage", 1.0, 2)}
HR_ZONES = {"lightTime": "light", "moderateTime": "moderate", "vigorousTime": "vigorous", "peakTime": "peak"}


# ------------------------------------------------------------------------------ chuyển kiểu
def _get(value: dict[str, Any], path: str) -> Any:
    node: Any = value
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _bounded(column: str, value: float | None, digits: int | None = None) -> float | int | None:
    if value is None:
        return None
    low, high = RANGES.get(column, (float("-inf"), float("inf")))
    if not low <= value <= high:
        return None
    return round(value) if digits is None else round(value, digits)


def _minutes(value: Any) -> int | None:
    minutes = number(value)
    return int(minutes) if minutes is not None and 0 <= minutes <= 2880 else None


def _entity(point: HealthPoint) -> dict[str, Any]:
    """Các trường EntityRead. Upsert theo tên Google giữ id ổn định qua các lần đồng bộ."""
    return {"id": point.id, "created_at": point.created_at, "updated_at": point.updated_at,
            "version_id": 1, "is_active": True}


# ------------------------------------------------------------------------------ ánh xạ theo loại
def daily_columns(data_type: str, value: dict[str, Any]) -> dict[str, Any]:
    """Các chỉ số theo ngày từ một điểm Daily (rollup ngày hoặc daily-*)."""
    if data_type == "steps":
        return {"steps": _bounded("steps", number(value.get("countSum")))}
    if data_type == "distance":
        mm = number(value.get("millimetersSum"))
        return {"distance_m": _bounded("distance_m", mm / 1000 if mm is not None else None, 2)}
    if data_type == "floors":
        return {"floors": _bounded("floors", number(value.get("countSum")))}
    if data_type == "active-zone-minutes":
        zones = [number(value.get(key)) for key in ("sumInFatBurnHeartZone", "sumInCardioHeartZone", "sumInPeakHeartZone")]
        known = [minutes for minutes in zones if minutes is not None]
        return {"active_zone_minutes": _bounded("active_zone_minutes", sum(known)) if known else None}
    if data_type == "total-calories":
        return {"total_kcal": _bounded("total_kcal", number(value.get("kcalSum")), 1)}
    if data_type == "active-energy-burned":
        return {"active_kcal": _bounded("active_kcal", number(value.get("kcalSum")), 1)}
    if data_type == "heart-rate":
        return {"hr_avg_bpm": _bounded("hr_avg_bpm", number(value.get("beatsPerMinuteAvg")), 1),
                "hr_min_bpm": _bounded("hr_min_bpm", number(value.get("beatsPerMinuteMin"))),
                "hr_max_bpm": _bounded("hr_max_bpm", number(value.get("beatsPerMinuteMax")))}
    if data_type == "active-minutes":
        levels: dict[str, int] = {}
        for entry in value.get("activeMinutesRollupByActivityLevel") or []:
            minutes = number((entry or {}).get("activeMinutesSum"))
            if (entry or {}).get("activityLevel") and minutes is not None:
                levels[entry["activityLevel"]] = levels.get(entry["activityLevel"], 0) + int(minutes)
        if not levels:
            return {}
        # Vận động nhẹ không tính vào khuyến nghị vận động vừa-mạnh của WHO.
        total = sum(minutes for level, minutes in levels.items() if level not in LIGHT_LEVELS)
        return {"active_minutes": _bounded("active_minutes", total), "active_minutes_by_level": levels}
    if data_type == "daily-resting-heart-rate":
        return {"resting_hr_bpm": _bounded("resting_hr_bpm", number(value.get("beatsPerMinute")))}
    if data_type == "daily-heart-rate-variability":
        return {"hrv_ms": _bounded("hrv_ms", number(value.get("averageHeartRateVariabilityMilliseconds")), 2)}
    if data_type == "daily-oxygen-saturation":
        return {"spo2_avg_pct": _bounded("spo2_avg_pct", number(value.get("averagePercentage")), 2)}
    if data_type == "daily-respiratory-rate":
        return {"respiratory_rate": _bounded("respiratory_rate", number(value.get("breathsPerMinute")), 2)}
    if data_type == "daily-vo2-max":
        return {"vo2_max": _bounded("vo2_max", number(value.get("vo2Max")), 2)}
    if data_type == "daily-sleep-temperature-derivations":
        nightly, baseline = number(value.get("nightlyTemperatureCelsius")), number(value.get("baselineTemperatureCelsius"))
        if nightly is not None and baseline is not None:
            return {"skin_temp_delta_c": _bounded("skin_temp_delta_c", nightly - baseline, 2)}
    return {}


ASLEEP_STAGES = {"ASLEEP", "LIGHT", "DEEP", "REM", "RESTLESS"}


def _stage_minutes(stages: list[Any], point: HealthPoint) -> tuple[int | None, int]:
    """(phút ngủ từ các đoạn ngủ, phút trên giường của cả khoảng) khi chưa có summary của Google."""
    asleep = 0.0
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("type") not in ASLEEP_STAGES:
            continue
        try:
            start = datetime.fromisoformat(str(stage["startTime"]))
            end = datetime.fromisoformat(str(stage["endTime"]))
        except (KeyError, ValueError):
            continue
        asleep += max(0.0, (end - start).total_seconds() / 60)
    in_period = round((point.end_at - point.start_at).total_seconds() / 60)
    return (round(asleep) if asleep else None), in_period


def sleep_row(point: HealthPoint) -> dict[str, Any] | None:
    if point.start_at is None or point.end_at is None or point.end_at <= point.start_at:
        return None
    value = point.value
    summary, metadata = value.get("summary") or {}, value.get("metadata") or {}
    stages = {item.get("type"): _minutes(item.get("minutes")) for item in summary.get("stagesSummary") or []
              if isinstance(item, dict)}
    asleep, in_period = _minutes(summary.get("minutesAsleep")), _minutes(summary.get("minutesInSleepPeriod"))
    if not summary:
        # Vừa ghi tay, Google chưa trả summary (trường output-only): suy ra từ các đoạn đã ghi.
        asleep, in_period = _stage_minutes(value.get("stages") or [], point)
    is_nap = bool(metadata.get("nap", False))
    return {
        **_entity(point), "source": HEALTH_PROVIDER, "start_at": point.start_at,
        "end_at": point.end_at, "local_date": point.local_date, "sleep_type": value.get("type"),
        "is_main": bool(metadata.get("mainSleep", not is_nap)), "is_nap": is_nap,
        "minutes_asleep": asleep, "minutes_awake": _minutes(summary.get("minutesAwake")),
        "minutes_in_period": in_period, "minutes_to_fall_asleep": _minutes(summary.get("minutesToFallAsleep")),
        "deep_minutes": stages.get("DEEP"), "light_minutes": stages.get("LIGHT"), "rem_minutes": stages.get("REM"),
        "awake_minutes": stages.get("AWAKE"),
        "efficiency_pct": round(min(100.0, 100 * asleep / in_period), 2) if asleep and in_period else None,
        "data_source": {"manual": True} if point.written_by_hercfit else {},
        # Chi tiết giữ nguyên: lần thức giấc ngắn có thể chồng lên giai đoạn, không bao giờ cộng vào tổng.
        "stages": value.get("stages") or [], "short_awakenings": value.get("shortAwakenings") or [],
    }


def workout_row(point: HealthPoint) -> dict[str, Any] | None:
    if point.start_at is None or point.end_at is None or point.end_at < point.start_at:
        return None
    value = point.value
    metrics = value.get("metricsSummary") or {}
    durations = metrics.get("heartRateZoneDurations") or {}
    zones = {label: round(seconds) for key, label in HR_ZONES.items()
             if (seconds := number(durations.get(key))) is not None}

    def bounded(raw: Any, low: float, high: float, digits: int | None = None, scale: float = 1.0):
        amount = number(raw)
        if amount is None or not low <= amount * scale <= high:
            return None
        return round(amount * scale) if digits is None else round(amount * scale, digits)

    return {
        **_entity(point), "source": HEALTH_PROVIDER, "started_at": point.start_at,
        "ended_at": point.end_at, "local_date": point.local_date, "exercise_type": value.get("exerciseType"),
        "display_name": (value.get("displayName") or "")[:255] or None,
        "active_seconds": bounded(value.get("activeDuration"), 0, 7 * 86400),
        "energy_kcal": bounded(metrics.get("caloriesKcal"), 0, 50_000, 1),
        "distance_m": bounded(metrics.get("distanceMillimeters"), 0, 1_000_000, 2, 0.001),
        "steps": bounded(metrics.get("steps"), 0, 1_000_000),
        "avg_hr_bpm": bounded(metrics.get("averageHeartRateBeatsPerMinute"), 20, 300),
        "active_zone_minutes": bounded(metrics.get("activeZoneMinutes"), 0, 2880),
        "hr_zone_seconds": zones,
        "elevation_gain_m": bounded(metrics.get("elevationGainMillimeters"), -100_000, 100_000, 2, 0.001),
        "avg_speed_mps": bounded(metrics.get("averageSpeedMillimetersPerSecond"), 0, 1000, 3, 0.001),
        "run_vo2_max": bounded(metrics.get("runVo2Max"), 0, 100, 2),
        "data_source": {"written_by_hercfit": True} if point.written_by_hercfit else {},
        "elapsed_seconds": round((point.end_at - point.start_at).total_seconds()),
        "splits": value.get("splitSummaries") or value.get("splits") or [],
        "has_route": bool((value.get("exerciseMetadata") or {}).get("hasGps")),
        "remote_name": point.remote_name, "written_by_hercfit": point.written_by_hercfit,
    }


def sample_row(point: HealthPoint) -> dict[str, Any] | None:
    sample_type, path, unit, details = SAMPLES[point.data_type]
    raw = number(_get(point.value, path))
    if raw is None or point.start_at is None:
        return None
    return {**_entity(point), "source": HEALTH_PROVIDER, "sample_type": sample_type,
            "measured_at": point.start_at, "value": Decimal(str(round(raw, 3))), "unit": unit,
            "details": {key: str(point.value[key]) for key in details if point.value.get(key)}}


def body_value(point: HealthPoint) -> tuple[str, float] | None:
    """(cột HercFit, giá trị) của một mẫu cân nặng / chiều cao / mỡ cơ thể."""
    column, field, factor, digits = BODY[point.data_type]
    raw = number(point.value.get(field))
    return (column, round(raw * factor, digits)) if raw is not None else None


# ------------------------------------------------------------------------------ truy vấn
async def points(session, user_id: UUID, data_types: Iterable[str], start: date, end: date) -> list[HealthPoint]:
    """Các điểm có ngày địa phương trong [start, end] (gồm cả hai đầu), cũ trước."""
    return list((await session.execute(select(HealthPoint).where(
        HealthPoint.user_id == user_id, HealthPoint.data_type.in_(list(data_types)),
        HealthPoint.local_date >= start, HealthPoint.local_date <= end,
    ).order_by(HealthPoint.local_date, HealthPoint.start_at, HealthPoint.id))).scalars())


def sleep_minutes(rows: list[dict[str, Any]]) -> dict[date, int]:
    """Số phút ngủ theo ngày thức dậy; không tính giấc ngủ ngắn ban ngày."""
    totals: dict[date, int] = defaultdict(int)
    for row in rows:
        if not row["is_nap"] and row.get("minutes_asleep") is not None:
            totals[row["local_date"]] += row["minutes_asleep"]
    return {day: minutes for day, minutes in totals.items() if minutes <= 1440}


async def daily(session, user_id: UUID, start: date, end: date, zone: str = DEFAULT_TIMEZONE) -> list[DailyHealthRead]:
    found = await points(session, user_id, DAILY_TYPES, start, end)
    by_day: dict[date, dict[str, Any]] = defaultdict(dict)
    stamps: dict[date, list[HealthPoint]] = defaultdict(list)
    sleeps = []
    for point in found:
        stamps[point.local_date].append(point)
        if point.data_type == "sleep":
            if (row := sleep_row(point)) is not None:
                sleeps.append(row)
        elif point.data_type == "hydration-log":
            ml = number(_get(point.value, "amountConsumed.milliliters"))
            if ml is not None:
                by_day[point.local_date]["hydration_ml"] = by_day[point.local_date].get("hydration_ml", 0) + ml
        elif point.data_type == "sedentary-period":
            if point.start_at and point.end_at:
                minutes = (point.end_at - point.start_at).total_seconds() / 60
                by_day[point.local_date]["sedentary_minutes"] = by_day[point.local_date].get("sedentary_minutes", 0) + minutes
        else:
            by_day[point.local_date].update({key: item for key, item in daily_columns(point.data_type, point.value).items()
                                             if item is not None})
    for day, minutes in sleep_minutes(sleeps).items():
        by_day[day]["sleep_minutes"] = minutes
    result = []
    for day in sorted(by_day):
        values = by_day[day]
        for column in ("hydration_ml", "sedentary_minutes"):
            if column in values:
                values[column] = _bounded(column, values[column], 1 if column == "hydration_ml" else None)
        first, last = min(stamps[day], key=lambda p: p.created_at), max(stamps[day], key=lambda p: p.updated_at)
        result.append(DailyHealthRead(
            id=uuid5(NAMESPACE, f"{user_id}:daily:{day.isoformat()}"), created_at=first.created_at,
            updated_at=last.updated_at, version_id=1, is_active=True, local_date=day, source=HEALTH_PROVIDER,
            timezone=zone, active_minutes_by_level=values.get("active_minutes_by_level", {}),
            **{field: values.get(field) for field in RANGES}))
    return result


async def sleep_rows(session, user_id: UUID, start: date, end: date) -> list[dict[str, Any]]:
    """Phiên ngủ kèm chi tiết (giai đoạn, lần thức giấc ngắn)."""
    rows = [sleep_row(point) for point in await points(session, user_id, ("sleep",), start, end)]
    return [row for row in rows if row is not None]


async def workout_rows(session, user_id: UUID, start: date, end: date, *,
                       types: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Buổi tập trên Google (thiết bị, ghi qua chat, ứng dụng khác) kèm chi tiết (splits)."""
    wanted = set(types) if types is not None else None
    rows = [workout_row(point) for point in await points(session, user_id, ("exercise",), start, end)]
    return [row for row in rows if row is not None and (wanted is None or row["exercise_type"] in wanted)]


async def sleep(session, user_id: UUID, start: date, end: date) -> list[SleepSessionRead]:
    return [SleepSessionRead.model_validate(row) for row in await sleep_rows(session, user_id, start, end)]


async def workouts(session, user_id: UUID, start: date, end: date, *,
                   types: Iterable[str] | None = None) -> list[DeviceWorkoutRead]:
    return [DeviceWorkoutRead.model_validate(row) for row in await workout_rows(session, user_id, start, end, types=types)]


async def samples(session, user_id: UUID, start: date, end: date, sample_type: str | None = None) -> list[HealthSampleRead]:
    data_types = [SAMPLE_TYPES[sample_type]] if sample_type else list(SAMPLES)
    rows = [sample_row(point) for point in await points(session, user_id, data_types, start, end)]
    return sorted((HealthSampleRead.model_validate(row) for row in rows if row is not None),
                  key=lambda row: row.measured_at)


async def sessions(session, user_id: UUID, data_type: str, start: date, end: date) -> list[dict[str, Any]]:
    """Phiên thô (ECG, IRN): giá trị Google cùng thời điểm; dạng sóng ECG đã bị bỏ khi đọc."""
    return [{"id": point.id, "started_at": point.start_at,
             "ended_at": point.end_at, "local_date": point.local_date, **point.value}
            for point in await points(session, user_id, (data_type,), start, end)]


# ------------------------------------------------------------------------------ calo
async def _unlinked_gym(session, user_id: UUID, start: date, end: date, zone: str) -> dict[date, float]:
    """kcal theo ngày của buổi gym local chưa gắn với một phiên đồng hồ (ports.linked_trainings)."""
    from domains.health_records import ports

    linked = await ports.linked_trainings(session, user_id)
    rows = (await session.execute(text("""
        SELECT id, (started_at AT TIME ZONE :zone)::date AS day, energy_kcal FROM trainings
        WHERE user_id = :user AND is_active AND energy_kcal IS NOT NULL
          AND (started_at AT TIME ZONE :zone)::date BETWEEN :start AND :end"""),
        {"user": user_id, "zone": zone, "start": start, "end": end})).all()
    totals: dict[date, float] = defaultdict(float)
    for row in rows:
        if row.id not in linked:
            totals[row.day] += float(row.energy_kcal)
    return totals


async def exercise_kcal(session, user_id: UUID, start: date, end: date, zone: str = DEFAULT_TIMEZONE) -> dict[date, float]:
    totals = await _unlinked_gym(session, user_id, start, end, zone)
    for workout in await workouts(session, user_id, start, end):
        if workout.energy_kcal is not None:
            totals[workout.local_date] = totals.get(workout.local_date, 0.0) + float(workout.energy_kcal)
    return {day: round(kcal, 1) for day, kcal in totals.items()}


async def energy_out(session, user_id: UUID, start: date, end: date, zone: str = DEFAULT_TIMEZONE) -> dict[date, float]:
    """Tổng năng lượng tiêu hao theo ngày; chỉ có ngày khi Google có total-calories."""
    totals = {row.local_date: float(row.total_kcal) for row in await daily(session, user_id, start, end, zone)
              if row.total_kcal is not None}
    manual = await _unlinked_gym(session, user_id, start, end, zone)
    for point in await points(session, user_id, ("exercise",), start, end):
        kcal = number(_get(point.value, "metricsSummary.caloriesKcal"))
        if point.written_by_hercfit and kcal is not None:
            manual[point.local_date] = manual.get(point.local_date, 0.0) + kcal
    return {day: round(kcal + manual.get(day, 0.0), 1) for day, kcal in totals.items()}


# ------------------------------------------------------------------------------ knowledge graph
async def kg_facts(session, user_id: UUID, start: date, end: date) -> dict[tuple[str, str], dict[str, Any]]:
    """Dữ kiện graph của [start, end]: {(loại, id): payload} với đúng tên trường DailyHealth/SleepSession/DeviceWorkout."""
    facts: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, rows in (("DailyHealth", await daily(session, user_id, start, end)),
                       ("SleepSession", await sleep(session, user_id, start, end)),
                       ("DeviceWorkout", await workouts(session, user_id, start, end))):
        for row in rows:
            facts[(kind, str(row.id))] = {**row.model_dump(mode="json"), "user_id": str(user_id)}
    return facts


async def publish_kg(session, user_id: UUID, start: date, end: date,
                     before: Iterable[tuple[str, str]] = ()) -> int:
    """Phát dữ kiện hiện tại của cửa sổ qua kg_publish_backend và tombstone những gì đã biến mất.

    `before` là các khoá (loại, id) của cửa sổ trước lần đồng bộ. Hàm SQL tự đổi thành
    tombstone khi người dùng chưa cho phép trợ lý dùng dữ liệu thiết bị.
    """
    facts = await kg_facts(session, user_id, start, end)
    gone = [(kind, {"id": item, "user_id": str(user_id), "version_id": 1})
            for kind, item in set(before) - set(facts)]
    for (kind, _item), payload in facts.items():
        await session.execute(text("SELECT kg_publish_backend(:kind, CAST(:data AS jsonb))"),
                              {"kind": kind, "data": json.dumps(payload, default=str)})
    for kind, payload in gone:
        await session.execute(text("SELECT kg_publish_backend(:kind, CAST(:data AS jsonb), true)"),
                              {"kind": kind, "data": json.dumps(payload)})
    return len(facts) + len(gone)


async def publish_all_kg(session, user_id: UUID) -> int:
    """Phát lại mọi dữ kiện thiết bị của người dùng (khi vừa cấp consent cho trợ lý)."""
    from sqlalchemy import func

    bounds = (await session.execute(select(func.min(HealthPoint.local_date), func.max(HealthPoint.local_date))
                                    .where(HealthPoint.user_id == user_id))).one()
    if bounds[0] is None:
        return 0
    return await publish_kg(session, user_id, bounds[0], bounds[1])
