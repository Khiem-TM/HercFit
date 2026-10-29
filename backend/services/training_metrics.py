"""Deterministic training formulas. Pure functions: no I/O, no ORM.

Every estimate returned here carries its method and inputs so a reader can
reproduce it. References:
- Epley (1985) one-repetition maximum estimate.
- ACSM's Guidelines for Exercise Testing and Prescription, metabolic equations.
- Compendium of Physical Activities (Herrmann et al., 2024) for MET values.
- Foster et al. (2001) session-RPE training load.
- Karvonen heart-rate reserve; Daniels' Running Formula pace zones; Riegel (1981).
"""

from __future__ import annotations

from typing import Any

from schemas.exercises import (
    ActivityIntensity, EnduranceActivity, EndurancePerformance, ExerciseKind, LoadMode,
    SetType, SportPerformance, StrengthPerformance, StrengthSet,
)

ESTIMATE_SOURCE = "HERCFIT_ESTIMATE"
WORK_SETS = frozenset({SetType.WORKING, SetType.BACKOFF, SetType.DROP, SetType.FAILURE})
E1RM_SETS = frozenset({SetType.WORKING, SetType.BACKOFF, SetType.FAILURE})
E1RM_MAX_REPS = 12
# Assumptions used only when a strength item has no measured duration.
SECONDS_PER_REP = 3.0
DEFAULT_REST = {SetType.WARMUP: 60.0}
DEFAULT_WORK_REST = 90.0
STRENGTH_MET = 3.5  # Compendium: resistance training, multiple exercises, 8-15 reps, varied resistance.
SPORT_MET = {ActivityIntensity.LIGHT: 4.0, ActivityIntensity.MODERATE: 6.0, ActivityIntensity.VIGOROUS: 8.0}


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


# --------------------------------------------------------------------------- strength

def effective_load(work_set: StrengthSet, bodyweight_kg: float | None = None) -> float | None:
    """External: bar/dumbbell load. Bodyweight: body + added load. Assisted: body - assistance."""
    body = work_set.bodyweight_kg or bodyweight_kg
    if work_set.load_mode == LoadMode.EXTERNAL:
        return work_set.weight_kg
    if body is None:
        return None
    if work_set.load_mode == LoadMode.BODYWEIGHT:
        return body + (work_set.weight_kg or 0)
    return max(body - (work_set.assistance_kg or 0), 0)


def estimate_1rm(load_kg: float, reps: int, rir: float | None = None) -> float | None:
    """Epley with reps-in-reserve folded into effective reps; None beyond 12 reps."""
    effective_reps = reps + (rir or 0)
    if load_kg <= 0 or effective_reps > E1RM_MAX_REPS:
        return None
    if effective_reps <= 1:
        return load_kg
    return load_kg * (1 + effective_reps / 30)


def is_hard_set(work_set: StrengthSet) -> bool:
    """A working set close to failure. Without RPE/RIR a working set counts as hard."""
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


# --------------------------------------------------------------------------- endurance

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


# --------------------------------------------------------------------------- energy

def _estimate(kcal: float, method: str, version: str, **inputs) -> dict[str, Any]:
    return {"kcal": round(kcal, 3), "source": ESTIMATE_SOURCE, "method": method,
            "method_version": version, "inputs": {k: v for k, v in inputs.items() if v is not None}}


def acsm_kcal(activity: EnduranceActivity, distance_m: float, seconds: float, gain_m: float | None, weight_kg: float) -> dict[str, Any]:
    """ACSM metabolic equations: VO2 (ml/kg/min) -> kcal = VO2 * kg * min / 200."""
    minutes = seconds / 60
    speed = distance_m / minutes  # m/min
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
    """Server-side energy estimate with provenance, or None when weight is unknown."""
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
        met = performance.met or configuration.get("default_met") or SPORT_MET[performance.intensity]
        return met_kcal(met, performance.duration_seconds, weight, "MET_SPORT", intensity=performance.intensity.value)
    seconds, basis = strength_duration(performance)
    return met_kcal(configuration.get("default_met") or STRENGTH_MET, seconds, weight, "MET_STRENGTH", duration_basis=basis)


def allocate_session_time(items: list[dict[str, Any]], session_seconds: float | None) -> None:
    """Spread unmeasured session time over strength items whose duration was estimated from sets.

    Set-based estimates ignore warm-up, transitions and longer rests; when the whole
    session duration is known, MET energy is recomputed on the allocated time.
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


# --------------------------------------------------------------------------- load & zones

def session_load(session_rpe: float | None, duration_seconds: float | None) -> float | None:
    """Foster session-RPE: CR-10 rating x minutes (arbitrary units)."""
    if session_rpe is None or not duration_seconds:
        return None
    return round(float(session_rpe) * float(duration_seconds) / 60, 3)


def hr_zones(max_hr: int, resting_hr: int | None = None) -> dict[str, list[int]]:
    """Five zones; Karvonen (heart-rate reserve) when resting HR is known, else %HRmax."""
    bounds = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
    if resting_hr:
        reserve = max_hr - resting_hr
        return {f"Z{i}": [round(resting_hr + lo * reserve), round(resting_hr + hi * reserve)] for i, (lo, hi) in enumerate(bounds, 1)}
    return {f"Z{i}": [round(lo * max_hr), round(hi * max_hr)] for i, (lo, hi) in enumerate(bounds, 1)}


# Pace multipliers relative to threshold pace (seconds/km); slower = larger.
PACE_ZONE_FACTORS = {"E": (1.22, 1.32), "M": (1.06, 1.10), "T": (0.98, 1.02), "I": (0.90, 0.94), "R": (0.84, 0.88)}


def pace_zones(threshold_pace_s_per_km: float) -> dict[str, list[int]]:
    """Daniels-style training paces derived from threshold pace: [fast, slow] s/km."""
    return {zone: [round(threshold_pace_s_per_km * lo), round(threshold_pace_s_per_km * hi)]
            for zone, (lo, hi) in PACE_ZONE_FACTORS.items()}


def riegel(time_seconds: float, distance_m: float, target_m: float, exponent: float = 1.06) -> float:
    return time_seconds * (target_m / distance_m) ** exponent


def threshold_from_race(distance_m: float, time_seconds: float) -> float:
    """Approximate threshold pace as the Riegel-predicted ~1-hour race pace."""
    # Threshold ~= race pace sustainable for ~60 min; solve distance for 3600 s.
    hour_distance = distance_m * (3600 / time_seconds) ** (1 / 1.06)
    return 3600 * 1000 / hour_distance
