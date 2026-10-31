"""Pure conversions from Google Health API JSON to HercFit rows.

Units: weight grams -> kg, distances millimetres -> m/cm, 64-bit integers arrive
as strings. Rollup value names follow `{field}_{aggregation}` but are not fully
documented, so numbers are located by a tolerant, case/underscore-insensitive key
search (e.g. countSum, count_sum or count). Implausible values are dropped rather
than violating storage constraints.
"""
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from models.health import DAILY_RANGES

META_KEYS = {"civilstarttime", "civilendtime", "name", "datasource"}


def camel(data_type: str) -> str:
    head, *rest = data_type.split("-")
    return head + "".join(part.title() for part in rest)


def _norm(key: str) -> str:
    return key.replace("_", "").lower()


def find(value: Any, *names: str) -> Any:
    """First value whose key matches any name, depth-first through nested objects."""
    wanted = [_norm(name) for name in names]
    if isinstance(value, dict):
        for name in wanted:
            for key, item in value.items():
                if _norm(key) == name and not isinstance(item, (dict, list)):
                    return item
        for item in value.values():
            if isinstance(item, dict):
                found = find(item, *names)
                if found is not None:
                    return found
    return None


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def seconds(value: Any) -> float | None:
    """Protobuf Duration JSON: "3.5s"."""
    if isinstance(value, str) and value.endswith("s"):
        return number(value[:-1])
    return number(value)


def as_date(value: Any) -> date | None:
    if isinstance(value, dict):
        inner = value.get("date") if isinstance(value.get("date"), dict) else value
        try:
            return date(int(inner["year"]), int(inner["month"]), int(inner["day"]))
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def as_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00")))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_date(moment: datetime, utc_offset: Any, zone: str) -> date:
    offset = seconds(utc_offset)
    if offset is not None:
        return (moment.astimezone(timezone.utc) + timedelta(seconds=offset)).date()
    return moment.astimezone(ZoneInfo(zone)).date()


def clean(field: str, value: float | None, digits: int | None = None) -> float | int | None:
    if value is None:
        return None
    low, high = DAILY_RANGES.get(field, (float("-inf"), float("inf")))
    if not low <= value <= high:
        return None
    return round(value) if digits is None else round(value, digits)


def data_source(point: dict[str, Any]) -> dict[str, str]:
    source = point.get("dataSource") or {}
    device = source.get("device") or {}
    values = {"platform": source.get("platform"), "recording_method": source.get("recordingMethod"),
              "device": device.get("displayName"), "manufacturer": device.get("manufacturer"),
              "form_factor": device.get("formFactor")}
    return {key: str(value)[:100] for key, value in values.items() if value}


def payload(point: dict[str, Any], data_type: str) -> dict[str, Any]:
    value = point.get(camel(data_type)) or point.get(data_type.replace("-", "_"))
    if isinstance(value, dict):
        return value
    # Rollups and unknown spellings: the single measurement object beside the metadata.
    candidates = [item for key, item in point.items() if _norm(key) not in META_KEYS and isinstance(item, dict)]
    return candidates[0] if len(candidates) == 1 else {}


# ---------------------------------------------------------------------------
# Daily rollups -> daily_health_summaries columns
# ---------------------------------------------------------------------------
# data type: [(column, candidate value names, scale, rounding digits or None for int)]
ROLLUPS: dict[str, list[tuple[str, tuple[str, ...], float, int | None]]] = {
    "steps": [("steps", ("countSum", "count"), 1, None)],
    "distance": [("distance_m", ("millimetersSum", "millimeters"), 0.001, 2)],
    "floors": [("floors", ("countSum", "count"), 1, None)],
    "active-zone-minutes": [("active_zone_minutes", ("activeZoneMinutesSum", "activeZoneMinutes"), 1, None)],
    "total-calories": [("total_kcal", ("kcalSum", "kcal"), 1, 1)],
    "active-energy-burned": [("active_kcal", ("kcalSum", "kcal"), 1, 1)],
    "heart-rate": [("hr_avg_bpm", ("beatsPerMinuteAvg", "beatsPerMinuteMean", "averageBeatsPerMinute"), 1, 1),
                   ("hr_min_bpm", ("beatsPerMinuteMin", "minBeatsPerMinute"), 1, None),
                   ("hr_max_bpm", ("beatsPerMinuteMax", "maxBeatsPerMinute"), 1, None)],
    "hydration-log": [("hydration_ml", ("millilitersSum", "milliliters"), 1, 1)],
}
# Light activity does not count toward the WHO moderate-to-vigorous guideline.
LIGHT_LEVELS = {"LIGHT", "LIGHTLY_ACTIVE", "SEDENTARY", "ACTIVITY_LEVEL_UNSPECIFIED"}


def _active_minutes(value: dict[str, Any]) -> dict[str, Any]:
    levels: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, list):
            for entry in item:
                if isinstance(entry, dict) and entry.get("activityLevel"):
                    minutes = number(find(entry, "activeMinutesSum", "activeMinutes", "minutes"))
                    if minutes is not None:
                        level = str(entry["activityLevel"]).upper()
                        levels[level] = levels.get(level, 0) + round(minutes)
    if levels:
        total = sum(minutes for level, minutes in levels.items() if level not in LIGHT_LEVELS)
        return {"active_minutes": clean("active_minutes", total), "active_minutes_by_level": levels}
    total = number(find(value, "activeMinutesSum", "activeMinutes"))
    return {"active_minutes": clean("active_minutes", total)} if total is not None else {}


def rollup_rows(data_type: str, points: list[dict[str, Any]]) -> dict[date, dict[str, Any]]:
    days: dict[date, dict[str, Any]] = {}
    for point in points:
        day = as_date(point.get("civilStartTime"))
        value = payload(point, data_type)
        if day is None or not value:
            continue  # An unset value means no manual or on-wrist data that day.
        if data_type == "active-minutes":
            fields = _active_minutes(value)
        else:
            fields = {}
            for column, names, scale, digits in ROLLUPS.get(data_type, []):
                raw = number(find(value, *names))
                fields[column] = clean(column, raw * scale if raw is not None else None, digits)
        fields = {key: item for key, item in fields.items() if item is not None}
        if fields:
            days.setdefault(day, {}).update(fields)
    return days


# ---------------------------------------------------------------------------
# Daily list types (one data point per date)
# ---------------------------------------------------------------------------
DAILY_POINTS: dict[str, list[tuple[str, tuple[str, ...], int | None]]] = {
    "daily-resting-heart-rate": [("resting_hr_bpm", ("beatsPerMinute",), None)],
    "daily-heart-rate-variability": [("hrv_ms", ("averageHeartRateVariabilityMilliseconds",), 2)],
    "daily-oxygen-saturation": [("spo2_avg_pct", ("averagePercentage",), 2)],
    "daily-respiratory-rate": [("respiratory_rate", ("breathsPerMinute",), 2)],
    "daily-vo2-max": [("vo2_max", ("vo2Max",), 2)],
}


def daily_rows(data_type: str, points: list[dict[str, Any]]) -> dict[date, dict[str, Any]]:
    days: dict[date, dict[str, Any]] = {}
    for point in points:
        value = payload(point, data_type)
        day = as_date(value.get("date"))
        if day is None:
            continue
        fields: dict[str, Any] = {}
        if data_type == "daily-sleep-temperature-derivations":
            nightly, baseline = number(value.get("nightlyTemperatureCelsius")), number(value.get("baselineTemperatureCelsius"))
            if nightly is not None and baseline is not None:
                fields["skin_temp_delta_c"] = clean("skin_temp_delta_c", nightly - baseline, 2)
        for column, names, digits in DAILY_POINTS.get(data_type, []):
            fields[column] = clean(column, number(find(value, *names)), digits)
        fields = {key: item for key, item in fields.items() if item is not None}
        if fields:
            days.setdefault(day, {}).update(fields)
    return days


# ---------------------------------------------------------------------------
# Body samples -> body_metrics rows
# ---------------------------------------------------------------------------
BODY_SAMPLES = {
    # data type: (column, value name, scale, plausible range)
    "weight": ("weight_kg", "weightGrams", 0.001, (2.0, 700.0)),
    "height": ("height_cm", "heightMillimeters", 0.1, (30.0, 300.0)),
    "body-fat": ("body_fat_pct", "percentage", 1, (1.0, 80.0)),
}


def _external_id(point: dict[str, Any], data_type: str, moment: datetime) -> str:
    return str(point.get("name") or f"{data_type}:{moment.isoformat()}")[:255]


def body_rows(data_type: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    column, name, scale, (low, high) = BODY_SAMPLES[data_type]
    rows = []
    for point in points:
        value = payload(point, data_type)
        moment = as_time((value.get("sampleTime") or {}).get("physicalTime"))
        raw = number(find(value, name))
        if moment is None or raw is None or not low <= raw * scale <= high:
            continue
        rows.append({"external_id": _external_id(point, data_type, moment), "recorded_at": moment,
                     column: round(raw * scale, 3 if column != "body_fat_pct" else 2),
                     "data_source": data_source(point)})
    return rows


# ---------------------------------------------------------------------------
# Spot vitals -> health_samples rows (PostgreSQL only)
# ---------------------------------------------------------------------------
SAMPLES = {
    "blood-glucose": ("BLOOD_GLUCOSE", "bloodGlucoseMilligramsPerDeciliter", "mg/dL", (10.0, 900.0),
                      ("mealType", "measurementTiming", "specimen", "measurementSource")),
    "core-body-temperature": ("CORE_BODY_TEMPERATURE", "temperatureCelsius", "C", (25.0, 45.0),
                              ("measurementLocation",)),
}


def sample_rows(data_type: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sample_type, name, unit, (low, high), detail_keys = SAMPLES[data_type]
    rows = []
    for point in points:
        value = payload(point, data_type)
        moment = as_time((value.get("sampleTime") or {}).get("physicalTime"))
        raw = number(value.get(name))
        if moment is None or raw is None or not low <= raw <= high:
            continue
        rows.append({"external_id": _external_id(point, data_type, moment), "sample_type": sample_type,
                     "measured_at": moment, "value": round(raw, 3), "unit": unit,
                     "details": {key: str(value[key]) for key in detail_keys if value.get(key)},
                     "data_source": data_source(point)})
    return rows


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _interval(value: dict[str, Any]) -> tuple[datetime, datetime, Any] | None:
    interval = value.get("interval") or {}
    start, end = as_time(interval.get("startTime")), as_time(interval.get("endTime"))
    if start is None or end is None or end <= start:
        return None
    return start, end, interval.get("endUtcOffset")


def _minutes(value: Any) -> int | None:
    result = number(value)
    return round(result) if result is not None and 0 <= result <= 2880 else None


def sleep_rows(points: list[dict[str, Any]], zone: str) -> list[dict[str, Any]]:
    rows = []
    for point in points:
        value = payload(point, "sleep")
        interval = _interval(value)
        if interval is None:
            continue
        start, end, end_offset = interval
        summary = value.get("summary") or {}
        metadata = value.get("metadata") or {}
        stages = {str(item.get("type", "")).upper(): _minutes(item.get("minutes"))
                  for item in summary.get("stagesSummary") or [] if isinstance(item, dict)}
        asleep, in_period = _minutes(summary.get("minutesAsleep")), _minutes(summary.get("minutesInSleepPeriod"))
        if asleep is None:
            asleep = round((end - start).total_seconds() / 60) if (end - start).total_seconds() <= 172800 else None
        rows.append({
            "external_id": _external_id(point, "sleep", start), "start_at": start, "end_at": end,
            "local_date": local_date(end, end_offset, zone), "sleep_type": str(value.get("type") or "")[:20] or None,
            "is_main": bool(metadata.get("mainSleep", not metadata.get("nap", False))),
            "is_nap": bool(metadata.get("nap", False)),
            "minutes_asleep": asleep, "minutes_awake": _minutes(summary.get("minutesAwake")),
            "minutes_in_period": in_period, "minutes_to_fall_asleep": _minutes(summary.get("minutesToFallAsleep")),
            "deep_minutes": stages.get("DEEP"), "light_minutes": stages.get("LIGHT"),
            "rem_minutes": stages.get("REM"), "awake_minutes": stages.get("AWAKE"),
            "efficiency_pct": round(min(100.0, 100 * asleep / in_period), 2) if asleep and in_period else None,
            "data_source": data_source(point),
        })
    return rows


ZONE_KEYS = {"lightTime": "light", "moderateTime": "moderate", "vigorousTime": "vigorous", "peakTime": "peak"}


def workout_rows(points: list[dict[str, Any]], zone: str) -> list[dict[str, Any]]:
    rows = []
    for point in points:
        value = payload(point, "exercise")
        interval = _interval(value)
        if interval is None:
            continue
        start, end, end_offset = interval
        metrics = value.get("metricsSummary") or {}
        zones = {label: round(s) for key, label in ZONE_KEYS.items()
                 if (s := seconds((metrics.get("heartRateZoneDurations") or {}).get(key))) is not None}
        active = seconds(value.get("activeDuration"))
        distance = number(metrics.get("distanceMillimeters"))
        elevation = number(metrics.get("elevationGainMillimeters"))
        speed = number(metrics.get("averageSpeedMillimetersPerSecond"))

        def bounded(raw, low, high, digits=None):
            if raw is None or not low <= raw <= high:
                return None
            return round(raw) if digits is None else round(raw, digits)

        rows.append({
            "external_id": _external_id(point, "exercise", start), "started_at": start, "ended_at": end,
            "local_date": local_date(start, (value.get("interval") or {}).get("startUtcOffset"), zone),
            "exercise_type": str(value.get("exerciseType") or "")[:64] or None,
            "display_name": str(value.get("displayName") or "")[:255] or None,
            "active_seconds": bounded(active, 0, 7 * 86400),
            "energy_kcal": bounded(number(metrics.get("caloriesKcal")), 0, 50_000, 1),
            "distance_m": bounded(distance / 1000 if distance is not None else None, 0, 1_000_000, 2),
            "steps": bounded(number(metrics.get("steps")), 0, 1_000_000),
            "avg_hr_bpm": bounded(number(metrics.get("averageHeartRateBeatsPerMinute")), 20, 300),
            "active_zone_minutes": bounded(number(metrics.get("activeZoneMinutes")), 0, 2880),
            "hr_zone_seconds": zones,
            "elevation_gain_m": bounded(elevation / 1000 if elevation is not None else None, -100_000, 100_000, 2),
            "avg_speed_mps": bounded(speed / 1000 if speed is not None else None, 0, 1000, 3),
            "run_vo2_max": bounded(number(metrics.get("runVo2Max")), 0, 100, 2),
            "data_source": data_source(point),
        })
    return rows


def main_sleep_minutes(rows: list[dict[str, Any]]) -> dict[date, int]:
    """Minutes asleep per wake-up date; naps are excluded."""
    totals: dict[date, int] = {}
    for row in rows:
        if not row["is_nap"] and row.get("minutes_asleep") is not None:
            totals[row["local_date"]] = totals.get(row["local_date"], 0) + row["minutes_asleep"]
    return {day: minutes for day, minutes in totals.items() if minutes <= 1440}


# ---------------------------------------------------------------------------
# Profile and settings
# ---------------------------------------------------------------------------
def provider_profile(profile: dict[str, Any] | None, settings: dict[str, Any] | None) -> dict[str, Any]:
    profile, settings = profile or {}, settings or {}
    membership = as_date(profile.get("membershipStartDate"))
    values = {
        "age": int(profile["age"]) if isinstance(profile.get("age"), (int, str)) and str(profile["age"]).isdigit() else None,
        "membership_start_date": membership.isoformat() if membership else None,
        "walking_stride_mm": profile.get("userConfiguredWalkingStrideLengthMm") or profile.get("autoWalkingStrideLengthMm"),
        "running_stride_mm": profile.get("userConfiguredRunningStrideLengthMm") or profile.get("autoRunningStrideLengthMm"),
        "weight_unit": settings.get("weightUnit"), "height_unit": settings.get("heightUnit"),
        "distance_unit": settings.get("distanceUnit"), "language_locale": settings.get("languageLocale"),
    }
    return {key: value for key, value in values.items() if value is not None}


def provider_timezone(settings: dict[str, Any] | None) -> str | None:
    zone = (settings or {}).get("timeZone")
    if not isinstance(zone, str):
        return None
    try:
        ZoneInfo(zone)
    except (ValueError, KeyError):  # ZoneInfoNotFoundError is a KeyError
        return None
    return zone
