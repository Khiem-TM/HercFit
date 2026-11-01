"""Phép chiếu tường minh từ các điểm Google Health đã phân tích sang dòng nghiệp vụ của HercFit.

Mỗi cột gọi tên đúng đường dẫn schema nó lấy từ đó (revision discovery trong
contract/registry.DISCOVERY_REVISION), thay cho việc tìm khoá dễ dãi của
mappers.py. Quy đổi đơn vị là tường minh: gam -> kg, milimét -> m hoặc cm,
thời lượng tính bằng giây. Giá trị mà adapter gắn cờ (BAD_TYPE, OUT_OF_RANGE) là
None ở đây, và cờ đi cùng bản ghi nguồn, nên "không có dữ liệu", "bằng 0"
và "bị từ chối" vẫn phân biệt được.

Ngày địa phương (theo đồng hồ) lấy từ thời điểm Google ghi cùng điểm dữ liệu
(giờ địa phương hoặc giờ vật lý + độ lệch UTC đã ghi); múi giờ *hiện tại* của người dùng
chỉ là phương án dự phòng cho điểm không có cả hai.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from domains.health_records.models.device_records import DAILY_RANGES
from integrations.google_health.adapters.base import Parsed

LIGHT_LEVELS = {"SEDENTARY", "LIGHTLY_ACTIVE", "LIGHT", "ACTIVITY_LEVEL_UNSPECIFIED"}


def _bounded(column: str, value: float | None, digits: int | None = None) -> float | int | None:
    if value is None:
        return None
    low, high = DAILY_RANGES.get(column, (float("-inf"), float("inf")))
    if not low <= value <= high:
        return None
    return round(value) if digits is None else round(value, digits)


def _scaled(value: Any, factor: float) -> float | None:
    return value * factor if isinstance(value, (int, float)) else None


def source_summary(parsed: Parsed) -> dict[str, str]:
    """JSON data_source gọn lưu trên dòng nghiệp vụ (nguồn gốc, không bao giờ là định danh)."""
    source = parsed.data_source or {}
    device = source.get("device") or {}
    application = source.get("application") or {}
    values = {"platform": source.get("platform"), "recording_method": source.get("recordingMethod"),
              "device": device.get("displayName"), "manufacturer": device.get("manufacturer"),
              "form_factor": device.get("formFactor"), "package": application.get("packageName"),
              "web_client": application.get("googleWebClientId")}
    return {key: str(value)[:100] for key, value in values.items() if value}


def civil_date(parsed: Parsed, fallback_zone: str, *, use_end: bool = False) -> date | None:
    if parsed.time.civil_date is not None and not use_end:
        return parsed.time.civil_date
    local = parsed.time.local_end() if use_end else parsed.time.local_start()
    if local is not None:
        return local.date()
    moment = parsed.time.physical_end if use_end else parsed.time.physical_start
    return moment.astimezone(ZoneInfo(fallback_zone)).date() if moment else None


# ---------------------------------------------------------------------------
# Các cột của daily_health_summaries
# ---------------------------------------------------------------------------
def rollup_columns(parsed: Parsed) -> dict[str, Any]:
    """Các cột từ một cửa sổ dailyRollUp (schema giá trị: <Type>RollupValue)."""
    value, kind = parsed.value, parsed.data_type
    if kind == "steps":
        return {"steps": _bounded("steps", value.get("countSum"))}
    if kind == "distance":
        return {"distance_m": _bounded("distance_m", _scaled(value.get("millimetersSum"), 0.001), 2)}
    if kind == "floors":
        return {"floors": _bounded("floors", value.get("countSum"))}
    if kind == "active-zone-minutes":
        zones = [value.get(key) for key in ("sumInFatBurnHeartZone", "sumInCardioHeartZone", "sumInPeakHeartZone")]
        known = [minutes for minutes in zones if isinstance(minutes, int)]
        return {"active_zone_minutes": _bounded("active_zone_minutes", sum(known)) if known else None}
    if kind == "total-calories":
        return {"total_kcal": _bounded("total_kcal", value.get("kcalSum"), 1)}
    if kind == "active-energy-burned":
        return {"active_kcal": _bounded("active_kcal", value.get("kcalSum"), 1)}
    if kind == "heart-rate":
        return {"hr_avg_bpm": _bounded("hr_avg_bpm", value.get("beatsPerMinuteAvg"), 1),
                "hr_min_bpm": _bounded("hr_min_bpm", value.get("beatsPerMinuteMin")),
                "hr_max_bpm": _bounded("hr_max_bpm", value.get("beatsPerMinuteMax"))}
    if kind == "hydration-log":
        amount = value.get("amountConsumed") or {}
        return {"hydration_ml": _bounded("hydration_ml", amount.get("millilitersSum"), 1)}
    if kind == "active-minutes":
        levels: dict[str, int] = {}
        for entry in value.get("activeMinutesRollupByActivityLevel") or []:
            if isinstance(entry, dict) and entry.get("activityLevel") and isinstance(entry.get("activeMinutesSum"), int):
                level = entry["activityLevel"]
                levels[level] = levels.get(level, 0) + entry["activeMinutesSum"]
        if not levels:
            return {}
        # Vận động nhẹ không tính vào khuyến nghị vận động vừa-mạnh của WHO.
        total = sum(minutes for level, minutes in levels.items() if level not in LIGHT_LEVELS)
        return {"active_minutes": _bounded("active_minutes", total), "active_minutes_by_level": levels}
    return {}


def daily_columns(parsed: Parsed) -> dict[str, Any]:
    """Các cột từ một data point daily-* (schema giá trị: Daily<Type>)."""
    value, kind = parsed.value, parsed.data_type
    if kind == "daily-resting-heart-rate":
        return {"resting_hr_bpm": _bounded("resting_hr_bpm", value.get("beatsPerMinute"))}
    if kind == "daily-heart-rate-variability":
        return {"hrv_ms": _bounded("hrv_ms", value.get("averageHeartRateVariabilityMilliseconds"), 2)}
    if kind == "daily-oxygen-saturation":
        return {"spo2_avg_pct": _bounded("spo2_avg_pct", value.get("averagePercentage"), 2)}
    if kind == "daily-respiratory-rate":
        return {"respiratory_rate": _bounded("respiratory_rate", value.get("breathsPerMinute"), 2)}
    if kind == "daily-vo2-max":
        return {"vo2_max": _bounded("vo2_max", value.get("vo2Max"), 2)}
    if kind == "daily-sleep-temperature-derivations":
        nightly, baseline = value.get("nightlyTemperatureCelsius"), value.get("baselineTemperatureCelsius")
        if isinstance(nightly, float) and isinstance(baseline, float):
            return {"skin_temp_delta_c": _bounded("skin_temp_delta_c", nightly - baseline, 2)}
    return {}


def merge_days(target: dict[date, dict[str, Any]], day: date | None, columns: dict[str, Any]) -> None:
    values = {key: item for key, item in columns.items() if item is not None}
    if day is not None and values:
        target.setdefault(day, {}).update(values)


# ---------------------------------------------------------------------------
# body_metrics, health_samples
# ---------------------------------------------------------------------------
BODY = {  # loại dữ liệu: (cột, đường dẫn giá trị, hệ số, số chữ số)
    "weight": ("weight_kg", "weightGrams", 0.001, 3),
    "height": ("height_cm", "heightMillimeters", 0.1, 3),
    "body-fat": ("body_fat_pct", "percentage", 1.0, 2),
}
SAMPLES = {  # loại dữ liệu: (sample_type, đường dẫn giá trị, đơn vị, các đường dẫn chi tiết)
    "blood-glucose": ("BLOOD_GLUCOSE", "bloodGlucoseMilligramsPerDeciliter", "mg/dL",
                      ("mealType", "measurementTiming", "specimen", "measurementSource")),
    "core-body-temperature": ("CORE_BODY_TEMPERATURE", "temperatureCelsius", "C", ("measurementLocation",)),
}
# Các chỉ số sinh tồn thưa mà pipeline job thêm vào (migration 0020 đã nới health_samples).
EXTRA_SAMPLES = {
    "vo2-max": ("VO2_MAX", "vo2Max", "mL/kg/min", ("measurementMethod",)),
    "run-vo2-max": ("RUN_VO2_MAX", "runVo2Max", "mL/kg/min", ()),
    "respiratory-rate-sleep-summary": ("SLEEP_RESPIRATORY_RATE", "fullSleepStats.breathsPerMinute", "breaths/min", ()),
}


def external_id(parsed: Parsed, moment: datetime | None) -> str:
    """Tên tài nguyên của Google khi loại có định danh, nếu không thì khoá ổn định loại+thời điểm."""
    if parsed.resource_name:
        return parsed.resource_name[:255]
    return f"{parsed.data_type}:{moment.isoformat() if moment else 'unknown'}"[:255]


def body_row(parsed: Parsed) -> dict[str, Any] | None:
    column, path, factor, digits = BODY[parsed.data_type]
    moment = parsed.time.physical_start
    raw = parsed.value.get(path)
    if moment is None or not isinstance(raw, (int, float)):
        return None
    return {"external_id": external_id(parsed, moment), "recorded_at": moment, column: round(raw * factor, digits),
            "data_source": source_summary(parsed)}


def sample_row(parsed: Parsed) -> dict[str, Any] | None:
    sample_type, path, unit, details = {**SAMPLES, **EXTRA_SAMPLES}[parsed.data_type]
    moment = parsed.time.physical_start
    raw = parsed.get(path)
    if moment is None or not isinstance(raw, (int, float)):
        return None
    return {"external_id": external_id(parsed, moment), "sample_type": sample_type, "measured_at": moment,
            "value": round(raw, 3), "unit": unit,
            "details": {key: str(parsed.value[key]) for key in details if parsed.value.get(key)},
            "data_source": source_summary(parsed), "utc_offset_s": parsed.time.start_offset_s}


# ---------------------------------------------------------------------------
# Phiên
# ---------------------------------------------------------------------------
def _minutes(value: Any) -> int | None:
    return value if isinstance(value, int) and 0 <= value <= 2880 else None


def _segments(items: list[Any] | None) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("startTime"), datetime) and isinstance(item.get("endTime"), datetime):
            out.append({"type": item.get("type"), "start": item["startTime"].isoformat(), "end": item["endTime"].isoformat(),
                        "seconds": round((item["endTime"] - item["startTime"]).total_seconds())})
    return out


def sleep_row(parsed: Parsed, fallback_zone: str) -> dict[str, Any] | None:
    start, end = parsed.time.physical_start, parsed.time.physical_end
    if start is None or end is None or end <= start:
        return None
    value = parsed.value
    summary = value.get("summary") or {}
    metadata = value.get("metadata") or {}
    stages = {item.get("type"): _minutes(item.get("minutes")) for item in summary.get("stagesSummary") or []
              if isinstance(item, dict)}
    asleep, in_period = _minutes(summary.get("minutesAsleep")), _minutes(summary.get("minutesInSleepPeriod"))
    is_nap = bool(metadata.get("nap", False))
    return {
        "external_id": external_id(parsed, start), "start_at": start, "end_at": end,
        # Một đêm thuộc ngày địa phương mà người dùng thức dậy.
        "local_date": civil_date(parsed, fallback_zone, use_end=True),
        "sleep_type": value.get("type"), "is_main": bool(metadata.get("mainSleep", not is_nap)), "is_nap": is_nap,
        "minutes_asleep": asleep, "minutes_awake": _minutes(summary.get("minutesAwake")),
        "minutes_in_period": in_period, "minutes_to_fall_asleep": _minutes(summary.get("minutesToFallAsleep")),
        "deep_minutes": stages.get("DEEP"), "light_minutes": stages.get("LIGHT"),
        "rem_minutes": stages.get("REM"), "awake_minutes": stages.get("AWAKE"),
        "efficiency_pct": round(min(100.0, 100 * asleep / in_period), 2) if asleep and in_period else None,
        "data_source": source_summary(parsed),
        # Chi tiết (cột M3): các đoạn được giữ nguyên. Lần thức giấc ngắn có thể
        # chồng lên giai đoạn, nên không bao giờ được cộng vào tổng giai đoạn.
        "stages": _segments(value.get("stages")), "short_awakenings": _segments(value.get("shortAwakenings")),
    }


ZONES = {"lightTime": "light", "moderateTime": "moderate", "vigorousTime": "vigorous", "peakTime": "peak"}


def _pauses(events: list[Any] | None) -> list[dict[str, Any]]:
    """Các cửa sổ tạm dừng từ sự kiện START/PAUSE/RESUME (thủ công và tự động)."""
    pauses, opened = [], None
    for event in sorted((e for e in events or [] if isinstance(e, dict) and isinstance(e.get("eventTime"), datetime)),
                        key=lambda e: e["eventTime"]):
        kind = event.get("exerciseEventType")
        if kind in ("PAUSE", "AUTO_PAUSE") and opened is None:
            opened = event
        elif kind in ("RESUME", "AUTO_RESUME", "STOP") and opened is not None:
            pauses.append({"start": opened["eventTime"].isoformat(), "end": event["eventTime"].isoformat(),
                           "auto": opened.get("exerciseEventType") == "AUTO_PAUSE",
                           "seconds": round((event["eventTime"] - opened["eventTime"]).total_seconds())})
            opened = None
    return pauses


def _split(item: dict[str, Any]) -> dict[str, Any]:
    metrics = item.get("metricsSummary") or {}
    distance = metrics.get("distanceMillimeters")
    return {"type": item.get("splitType"),
            "start": item["startTime"].isoformat() if isinstance(item.get("startTime"), datetime) else None,
            "end": item["endTime"].isoformat() if isinstance(item.get("endTime"), datetime) else None,
            "active_seconds": item.get("activeDuration"),
            "distance_m": round(distance / 1000, 2) if isinstance(distance, float) else None,
            "avg_hr_bpm": metrics.get("averageHeartRateBeatsPerMinute"),
            "pace_s_per_km": round(metrics["averagePaceSecondsPerMeter"] * 1000, 1)
            if isinstance(metrics.get("averagePaceSecondsPerMeter"), float) else None,
            "kcal": metrics.get("caloriesKcal")}


def workout_row(parsed: Parsed, fallback_zone: str) -> dict[str, Any] | None:
    start, end = parsed.time.physical_start, parsed.time.physical_end
    if start is None or end is None or end < start:
        return None
    value = parsed.value
    metrics = value.get("metricsSummary") or {}
    durations = metrics.get("heartRateZoneDurations") or {}
    zones = {label: round(seconds) for key, label in ZONES.items()
             if isinstance(seconds := durations.get(key), float)}

    def bounded(raw: Any, low: float, high: float, digits: int | None = None):
        if not isinstance(raw, (int, float)) or not low <= raw <= high:
            return None
        return round(raw) if digits is None else round(raw, digits)

    distance, elevation, speed = (metrics.get("distanceMillimeters"), metrics.get("elevationGainMillimeters"),
                                  metrics.get("averageSpeedMillimetersPerSecond"))
    return {
        "external_id": external_id(parsed, start), "started_at": start, "ended_at": end,
        "local_date": civil_date(parsed, fallback_zone),
        "exercise_type": value.get("exerciseType"), "display_name": (value.get("displayName") or "")[:255] or None,
        "active_seconds": bounded(value.get("activeDuration"), 0, 7 * 86400),
        "energy_kcal": bounded(metrics.get("caloriesKcal"), 0, 50_000, 1),
        "distance_m": bounded(_scaled(distance, 0.001), 0, 1_000_000, 2),
        "steps": bounded(metrics.get("steps"), 0, 1_000_000),
        "avg_hr_bpm": bounded(metrics.get("averageHeartRateBeatsPerMinute"), 20, 300),
        "active_zone_minutes": bounded(metrics.get("activeZoneMinutes"), 0, 2880),
        "hr_zone_seconds": zones,
        "elevation_gain_m": bounded(_scaled(elevation, 0.001), -100_000, 100_000, 2),
        "avg_speed_mps": bounded(_scaled(speed, 0.001), 0, 1000, 3),
        "run_vo2_max": bounded(metrics.get("runVo2Max"), 0, 100, 2),
        "data_source": source_summary(parsed),
        # Chi tiết (cột M3). Phiên của thiết bị không có set/số lần; không bịa ra cái nào.
        "elapsed_seconds": round((end - start).total_seconds()),
        "pauses": _pauses(value.get("exerciseEvents")),
        "splits": [_split(item) for item in (value.get("splitSummaries") or value.get("splits") or [])
                   if isinstance(item, dict)],
        "has_route": bool((value.get("exerciseMetadata") or {}).get("hasGps")),
    }


def main_sleep_minutes(rows: list[dict[str, Any]]) -> dict[date, int]:
    """Số phút ngủ theo ngày thức dậy; không tính giấc ngủ ngắn ban ngày."""
    totals: dict[date, int] = {}
    for row in rows:
        if not row["is_nap"] and row.get("minutes_asleep") is not None and row.get("local_date") is not None:
            totals[row["local_date"]] = totals.get(row["local_date"], 0) + row["minutes_asleep"]
    return {day: minutes for day, minutes in totals.items() if minutes <= 1440}


def utc_offset(parsed: Parsed) -> timedelta | None:
    return timedelta(seconds=parsed.time.start_offset_s) if parsed.time.start_offset_s is not None else None


# ---------------------------------------------------------------------------
# Hồ sơ và cài đặt (users.getProfile / users.getSettings)
# ---------------------------------------------------------------------------
def provider_profile(profile: dict[str, Any] | None, settings: dict[str, Any] | None) -> dict[str, Any]:
    profile, settings = profile or {}, settings or {}
    membership = profile.get("membershipStartDate") or {}
    try:
        started = date(int(membership["year"]), int(membership["month"]), int(membership["day"])).isoformat()
    except (KeyError, TypeError, ValueError):
        started = None
    age = profile.get("age")
    values = {
        "age": age if isinstance(age, int) and not isinstance(age, bool) and 0 < age < 130 else None,
        "membership_start_date": started,
        "walking_stride_mm": profile.get("userConfiguredWalkingStrideLengthMm") or profile.get("autoWalkingStrideLengthMm"),
        "running_stride_mm": profile.get("userConfiguredRunningStrideLengthMm") or profile.get("autoRunningStrideLengthMm"),
        "weight_unit": settings.get("weightUnit"), "height_unit": settings.get("heightUnit"),
        "distance_unit": settings.get("distanceUnit"), "water_unit": settings.get("waterUnit"),
        "glucose_unit": settings.get("glucoseUnit"), "language_locale": settings.get("languageLocale"),
    }
    return {key: value for key, value in values.items() if value is not None}


def provider_timezone(settings: dict[str, Any] | None) -> str | None:
    zone = (settings or {}).get("timeZone")
    if not isinstance(zone, str):
        return None
    try:
        ZoneInfo(zone)
    except (ValueError, KeyError):  # ZoneInfoNotFoundError là một KeyError
        return None
    return zone


# ---------------------------------------------------------------------------
# Nhật ký ECG, IRN, nước uống và dinh dưỡng (pipeline job, migration 0020)
# ---------------------------------------------------------------------------
def ecg_row(parsed: Parsed, fallback_zone: str) -> dict[str, Any] | None:
    """Phân loại và metadata của nhà cung cấp. Dạng sóng được trả về riêng và không bao giờ được chiếu thêm."""
    start, end = parsed.time.physical_start, parsed.time.physical_end
    if start is None or end is None:
        return None
    value = parsed.value
    device = value.get("medicalDeviceInfo") or {}
    samples = value.get("waveformSamples") or []
    return {"external_id": external_id(parsed, start), "started_at": start, "ended_at": end,
            "utc_offset_s": parsed.time.start_offset_s, "local_date": civil_date(parsed, fallback_zone),
            "classification": value.get("resultClassification"), "avg_hr_bpm": value.get("beatsPerMinuteAvg"),
            "sampling_hz": value.get("samplingFrequencyHertz"), "lead_number": value.get("leadNumber"),
            "device_model": (device.get("deviceModel") or "")[:120] or None,
            "algorithm_version": (device.get("algorithmVersion") or "")[:60] or None,
            "waveform_samples": len(samples) if isinstance(samples, list) else None}


def ecg_waveform(parsed: Parsed) -> list[int]:
    samples = parsed.value.get("waveformSamples") or []
    return [int(item) for item in samples if isinstance(item, int)]


def irn_row(parsed: Parsed, fallback_zone: str) -> dict[str, Any] | None:
    start, end = parsed.time.physical_start, parsed.time.physical_end
    if start is None or end is None:
        return None
    value = parsed.value
    device = value.get("medicalDeviceInfo") or {}
    windows = [{"start": w["startTime"].isoformat() if isinstance(w.get("startTime"), datetime) else None,
                "end": w["endTime"].isoformat() if isinstance(w.get("endTime"), datetime) else None,
                "positive": bool(w.get("positive"))}  # từng nhịp tim riêng lẻ ở lại trong bản ghi nguồn
               for w in value.get("alertWindows") or [] if isinstance(w, dict)]
    return {"external_id": external_id(parsed, start), "started_at": start, "ended_at": end,
            "utc_offset_s": parsed.time.start_offset_s, "local_date": civil_date(parsed, fallback_zone),
            "positive_windows": sum(1 for w in windows if w["positive"]), "windows": windows,
            "device_model": (device.get("deviceModel") or "")[:120] or None,
            "algorithm_version": (device.get("algorithmVersion") or "")[:60] or None}


def hydration_row(parsed: Parsed, fallback_zone: str) -> dict[str, Any] | None:
    start = parsed.time.physical_start
    amount = (parsed.value.get("amountConsumed") or {})
    millilitres = amount.get("milliliters")
    if start is None or not isinstance(millilitres, float) or not 0 < millilitres <= 10_000:
        return None
    return {"external_id": external_id(parsed, start), "consumed_at": start, "utc_offset_s": parsed.time.start_offset_s,
            "local_date": civil_date(parsed, fallback_zone), "amount_ml": round(millilitres, 1),
            "user_unit": amount.get("userProvidedUnit")}


def nutrition_row(parsed: Parsed, fallback_zone: str) -> dict[str, Any] | None:
    start = parsed.time.physical_start
    if start is None:
        return None
    value = parsed.value
    grams = {key: (value.get(key) or {}).get("grams") for key in ("totalCarbohydrate", "totalFat")}
    nutrients = {item["nutrient"]: (item.get("quantity") or {}).get("grams")
                 for item in value.get("nutrients") or [] if isinstance(item, dict) and item.get("nutrient")}
    protein = nutrients.get("PROTEIN")
    serving = value.get("serving") or {}
    return {"external_id": external_id(parsed, start), "consumed_at": start, "ended_at": parsed.time.physical_end,
            "utc_offset_s": parsed.time.start_offset_s, "local_date": civil_date(parsed, fallback_zone),
            "meal_type": value.get("mealType"), "food_name": (value.get("foodDisplayName") or "")[:255] or None,
            "energy_kcal": (value.get("energy") or {}).get("kcal"), "protein_g": protein,
            "carbohydrate_g": grams["totalCarbohydrate"], "fat_g": grams["totalFat"],
            "nutrients": {key: grams_value for key, grams_value in nutrients.items() if grams_value is not None},
            "serving": {"amount": serving.get("amount"), "unit": serving.get("foodMeasurementUnitDisplayName")}}
