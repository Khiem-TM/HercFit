"""Công thức tập luyện tất định. Hàm thuần: không I/O, không ORM.

Mọi ước tính trả về ở đây mang phương pháp và đầu vào để người đọc
tái tạo được. Tài liệu tham khảo:
- Epley (1985) ước tính 1RM.
- ACSM's Guidelines for Exercise Testing and Prescription, các phương trình chuyển hoá.
- Compendium of Physical Activities (Herrmann và cộng sự, 2024) cho giá trị MET.
- Foster và cộng sự (2001) tải tập session-RPE.
- Nhịp tim dự trữ Karvonen; vùng pace theo Daniels' Running Formula; Riegel (1981).
"""

from __future__ import annotations

from typing import Any

from domains.catalog.schemas.exercises import (
    ActivityIntensity,
    EnduranceActivity,
    EndurancePerformance,
    ExerciseKind,
    LoadMode,
    SetType,
    SportPerformance,
    StrengthPerformance,
    StrengthSet,
)

ESTIMATE_SOURCE = "HERCFIT_ESTIMATE"
WORK_SETS = frozenset({SetType.WORKING, SetType.BACKOFF, SetType.DROP, SetType.FAILURE})
E1RM_SETS = frozenset({SetType.WORKING, SetType.BACKOFF, SetType.FAILURE})
E1RM_MAX_REPS = 12
# Giả định chỉ dùng khi một mục sức mạnh không có thời lượng đo được.
SECONDS_PER_REP = 3.0
DEFAULT_REST = {SetType.WARMUP: 60.0}
DEFAULT_WORK_REST = 90.0
STRENGTH_MET = 3.5  # Compendium: tập kháng lực, nhiều bài, 8-15 lần, mức tạ thay đổi.
SPORT_MET = {ActivityIntensity.LIGHT: 4.0, ActivityIntensity.MODERATE: 6.0, ActivityIntensity.VIGOROUS: 8.0}
# Buổi gym chỉ ghi theo cường độ (môn thể thao "resistance_training" trong catalog), 2024 Adult Compendium:
# 02054 nhiều bài, 8-15 lần (3.5); 02061 tập gym/tạ, chung (5.0); 02050 cử tạ hoặc
# thể hình, mạnh (6.0).
RESISTANCE_MET = {ActivityIntensity.LIGHT: 3.5, ActivityIntensity.MODERATE: 5.0, ActivityIntensity.VIGOROUS: 6.0}
INTENSITY_MET = {"resistance_training": RESISTANCE_MET}


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


# --------------------------------------------------------------------------- sức mạnh

def effective_load(work_set: StrengthSet, bodyweight_kg: float | None = None) -> float | None:
    """Ngoài: tạ đòn/tạ đơn. Trọng lượng cơ thể: cơ thể + tạ thêm. Có hỗ trợ: cơ thể - phần hỗ trợ."""
    body = work_set.bodyweight_kg or bodyweight_kg
    if work_set.load_mode == LoadMode.EXTERNAL:
        return work_set.weight_kg
    if body is None:
        return None
    if work_set.load_mode == LoadMode.BODYWEIGHT:
        return body + (work_set.weight_kg or 0)
    return max(body - (work_set.assistance_kg or 0), 0)


def estimate_1rm(load_kg: float, reps: int, rir: float | None = None) -> float | None:
    """Epley với số lần dự trữ (RIR) gộp vào số lần hiệu dụng; None khi quá 12 lần."""
    effective_reps = reps + (rir or 0)
    if load_kg <= 0 or effective_reps > E1RM_MAX_REPS:
        return None
    if effective_reps <= 1:
        return load_kg
    return load_kg * (1 + effective_reps / 30)


def is_hard_set(work_set: StrengthSet) -> bool:
    """Set làm việc gần tới giới hạn. Khi không có RPE/RIR thì set làm việc được tính là nặng."""
    if work_set.set_type not in WORK_SETS:
        return False
    if work_set.set_type == SetType.FAILURE:
        return True
    if work_set.rpe is None and work_set.rir is None:
        return True
    return (work_set.rpe is not None and work_set.rpe >= 7) or (work_set.rir is not None and work_set.rir <= 3)


def strength_duration(performance: StrengthPerformance) -> tuple[float, str]:
    if performance.duration_seconds:
        return performance.duration_seconds, "measured"
    total = 0.0
    for work_set in performance.sets:
        work = work_set.hold_seconds or (work_set.reps or 0) * SECONDS_PER_REP
        rest = work_set.rest_seconds if work_set.rest_seconds is not None else DEFAULT_REST.get(work_set.set_type, DEFAULT_WORK_REST)
        total += work + rest
    return total, "estimated_from_sets"


def strength_metrics(performance: StrengthPerformance, *, e1rm_eligible: bool, bodyweight_kg: float | None) -> dict[str, Any]:
    volume, best, hard, working = 0.0, None, 0, 0
    for work_set in performance.sets:
        load = effective_load(work_set, bodyweight_kg)
        if work_set.set_type in WORK_SETS:
            working += 1
            if load is not None and work_set.reps:
                volume += load * work_set.reps
        hard += is_hard_set(work_set)
        if e1rm_eligible and load and work_set.reps and work_set.set_type in E1RM_SETS:
            estimate = estimate_1rm(load, work_set.reps, work_set.rir)
            if estimate is not None and (best is None or estimate > best):
                best = estimate
    duration, _basis = strength_duration(performance)
    return {
        "duration_seconds": _round(duration), "distance_meters": None, "elevation_gain_meters": None,
        "volume_kg": _round(volume), "best_e1rm_kg": _round(best), "hard_sets": hard, "working_sets": working,
    }


# --------------------------------------------------------------------------- sức bền

def pace_seconds_per_km(duration_seconds: float, distance_meters: float) -> float:
    return duration_seconds * 1000 / distance_meters


def endurance_metrics(performance: EndurancePerformance) -> dict[str, Any]:
    return {
        "duration_seconds": _round(performance.moving_seconds or performance.duration_seconds),
        "distance_meters": _round(performance.distance_meters),
        "elevation_gain_meters": _round(performance.elevation_gain_meters),
        "volume_kg": None, "best_e1rm_kg": None, "hard_sets": None, "working_sets": None,
    }


def sport_metrics(performance: SportPerformance) -> dict[str, Any]:
    return {
        "duration_seconds": _round(performance.duration_seconds), "distance_meters": _round(performance.distance_meters),
        "elevation_gain_meters": None, "volume_kg": None, "best_e1rm_kg": None, "hard_sets": None, "working_sets": None,
    }


def item_metrics(performance, configuration: dict[str, Any], *, bodyweight_kg: float | None) -> dict[str, Any]:
    if performance.kind == ExerciseKind.STRENGTH:
        return strength_metrics(performance, e1rm_eligible=bool(configuration.get("e1rm_eligible")), bodyweight_kg=bodyweight_kg)
    if performance.kind == ExerciseKind.ENDURANCE:
        return endurance_metrics(performance)
    return sport_metrics(performance)


# --------------------------------------------------------------------------- năng lượng

def _estimate(kcal: float, method: str, version: str, **inputs) -> dict[str, Any]:
    return {"kcal": round(kcal, 3), "source": ESTIMATE_SOURCE, "method": method,
            "method_version": version, "inputs": {k: v for k, v in inputs.items() if v is not None}}


def acsm_kcal(activity: EnduranceActivity, distance_m: float, seconds: float, gain_m: float | None, weight_kg: float) -> dict[str, Any]:
    """Phương trình chuyển hoá ACSM: VO2 (ml/kg/phút) -> kcal = VO2 * kg * phút / 200."""
    minutes = seconds / 60
    speed = distance_m / minutes  # m/phút
    grade = min((gain_m or 0) / distance_m, 0.4)
    if activity == EnduranceActivity.RUN:
        vo2 = 0.2 * speed + 0.9 * speed * grade + 3.5
        method = "ACSM_RUNNING"
    else:
        vo2 = 0.1 * speed + 1.8 * speed * grade + 3.5
        method = "ACSM_WALKING"
    return _estimate(vo2 * weight_kg * minutes / 200, method, "acsm-11", distance_meters=distance_m,
                     duration_seconds=seconds, grade=round(grade, 4), weight_kg=weight_kg, vo2_ml_kg_min=round(vo2, 2))


def met_kcal(met: float, seconds: float, weight_kg: float, method: str, **inputs) -> dict[str, Any]:
    return _estimate(met * weight_kg * seconds / 3600, method, "compendium-2024", met=met,
                     duration_seconds=round(seconds, 3), weight_kg=weight_kg, **inputs)


def estimate_kcal(performance, configuration: dict[str, Any], weight_kg: float | None) -> dict[str, Any] | None:
    """Ước tính năng lượng phía server kèm nguồn gốc, hoặc None khi chưa biết cân nặng."""
    weight = getattr(performance, "weight_kg", None) or weight_kg
    if weight is None:
        return None
    if performance.kind == ExerciseKind.ENDURANCE:
        activity = EnduranceActivity(configuration.get("activity", EnduranceActivity.OTHER))
        seconds = performance.moving_seconds or performance.duration_seconds
        if activity in {EnduranceActivity.RUN, EnduranceActivity.WALK, EnduranceActivity.HIKE}:
            return acsm_kcal(activity, performance.distance_meters, seconds, performance.elevation_gain_meters, weight)
        met = configuration.get("default_met")
        return met_kcal(met, seconds, weight, "MET_ENDURANCE") if met else None
    if performance.kind == ExerciseKind.SPORT:
        table = INTENSITY_MET.get(configuration.get("sport"), SPORT_MET)
        met = performance.met or configuration.get("default_met") or table[performance.intensity]
        return met_kcal(met, performance.duration_seconds, weight, "MET_SPORT", intensity=performance.intensity.value)
    seconds, basis = strength_duration(performance)
    return met_kcal(configuration.get("default_met") or STRENGTH_MET, seconds, weight, "MET_STRENGTH", duration_basis=basis)


def allocate_session_time(items: list[dict[str, Any]], session_seconds: float | None) -> None:
    """Rải thời gian buổi tập chưa đo cho các mục sức mạnh có thời lượng ước tính từ số set.

    Ước tính theo set bỏ qua khởi động, thời gian chuyển và các lần nghỉ dài; khi biết
    thời lượng cả buổi, năng lượng MET được tính lại trên thời gian đã phân bổ.
    """
    estimated = [item for item in items if (item.get("calorie_estimate") or {}).get("inputs", {}).get("duration_basis") == "estimated_from_sets"]
    if not session_seconds or not estimated:
        return
    measured = sum(float(item["duration_seconds"] or 0) for item in items if item not in estimated)
    remaining = session_seconds - measured
    estimate_total = sum(float(item["duration_seconds"] or 0) for item in estimated)
    if remaining <= estimate_total or estimate_total <= 0:
        return
    for item in estimated:
        inputs = item["calorie_estimate"]["inputs"]
        seconds = float(item["duration_seconds"]) * remaining / estimate_total
        item["calorie_estimate"] = met_kcal(inputs["met"], seconds, inputs["weight_kg"], "MET_STRENGTH", duration_basis="allocated_from_session")
        item["duration_seconds"] = round(seconds, 3)


# --------------------------------------------------------------------------- tải và vùng

def session_load(session_rpe: float | None, duration_seconds: float | None) -> float | None:
    """Session-RPE của Foster: điểm CR-10 x số phút (đơn vị tuỳ ý)."""
    if session_rpe is None or not duration_seconds:
        return None
    return round(float(session_rpe) * float(duration_seconds) / 60, 3)


def hr_zones(max_hr: int, resting_hr: int | None = None) -> dict[str, list[int]]:
    """Năm vùng; Karvonen (nhịp tim dự trữ) khi biết nhịp tim nghỉ, nếu không thì %HRmax."""
    bounds = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
    if resting_hr:
        reserve = max_hr - resting_hr
        return {f"Z{i}": [round(resting_hr + lo * reserve), round(resting_hr + hi * reserve)] for i, (lo, hi) in enumerate(bounds, 1)}
    return {f"Z{i}": [round(lo * max_hr), round(hi * max_hr)] for i, (lo, hi) in enumerate(bounds, 1)}


# Hệ số pace so với pace ngưỡng (giây/km); chậm hơn = lớn hơn.
PACE_ZONE_FACTORS = {"E": (1.22, 1.32), "M": (1.06, 1.10), "T": (0.98, 1.02), "I": (0.90, 0.94), "R": (0.84, 0.88)}


def pace_zones(threshold_pace_s_per_km: float) -> dict[str, list[int]]:
    """Pace tập kiểu Daniels suy ra từ pace ngưỡng: [nhanh, chậm] giây/km."""
    return {zone: [round(threshold_pace_s_per_km * lo), round(threshold_pace_s_per_km * hi)]
            for zone, (lo, hi) in PACE_ZONE_FACTORS.items()}


def riegel(time_seconds: float, distance_m: float, target_m: float, exponent: float = 1.06) -> float:
    return time_seconds * (target_m / distance_m) ** exponent


def threshold_from_race(distance_m: float, time_seconds: float) -> float:
    """Xấp xỉ pace ngưỡng bằng pace thi đấu ~1 giờ dự đoán theo Riegel."""
    # Ngưỡng ~= pace thi đấu duy trì được ~60 phút; giải quãng đường cho 3600 s.
    hour_distance = distance_m * (3600 / time_seconds) ** (1 / 1.06)
    return 3600 * 1000 / hour_distance
