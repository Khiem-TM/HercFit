"""Build Google Health DataPoint payloads for HercFit-owned records.

* Only what HercFit actually holds is sent: a training exports its session summary
  (interval, type, active duration, kcal), never invented heart-rate or step series.
* Each exported record gets a stable client id (HercFit's own key for the mapping row).
  Google assigns its own data point ids and ignores a client-provided name (real
  account, 2026-11-01), so an unknown create outcome is verified by content instead
  (dispatch._find_written) and creates are never retried blindly.
* Payloads are validated against the discovery schema by tests (the adapter must
  parse them without unknown fields or bad types).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

AGGREGATE_GROUPS = {
    "BodyMetric": "body", "HydrationLog": "hydration", "NutritionLog": "nutrition", "Meal": "nutrition",
    "Training": "workout", "SymptomLog": "symptoms", "MoodLog": "mood", "MenstrualPeriodLog": "reproductive",
    "OvulationTestLog": "reproductive",
}
DISCIPLINE_TYPES = {"STRENGTH": "STRENGTH_TRAINING", "ENDURANCE": "RUNNING", "SPORT": "SPORT", "MIXED": "WORKOUT"}


def client_id(aggregate_type: str, aggregate_id: Any, data_type: str) -> str:
    digest = hashlib.sha256(f"{aggregate_type}:{aggregate_id}:{data_type}".encode()).hexdigest()[:40]
    return f"hf-{digest}"


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stamp(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def _offset(moment: datetime, zone: str | None) -> str:
    local = moment.astimezone(ZoneInfo(zone or "Asia/Ho_Chi_Minh"))
    return f"{int(local.utcoffset().total_seconds())}s"


def _sample(moment: datetime, zone: str | None) -> dict[str, str]:
    return {"physicalTime": _stamp(moment), "utcOffset": _offset(moment, zone)}


def _interval(start: datetime, end: datetime, zone: str | None) -> dict[str, str]:
    return {"startTime": _stamp(start), "startUtcOffset": _offset(start, zone),
            "endTime": _stamp(end), "endUtcOffset": _offset(end, zone)}


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float, Decimal)) else None


MANUAL = {"recordingMethod": "MANUAL"}


def body_metric(entity, zone: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    """One body metric row can hold weight, height and body fat: one data point per measure."""
    points = []
    sample = _sample(entity.recorded_at, zone)
    if entity.weight_kg is not None:
        points.append(("weight", {"dataSource": MANUAL, "weight": {"weightGrams": round(float(entity.weight_kg) * 1000, 1),
                                                                    "sampleTime": sample}}))
    if entity.height_cm is not None:
        points.append(("height", {"dataSource": MANUAL, "height": {"heightMillimeters": str(round(float(entity.height_cm) * 10)),
                                                                    "sampleTime": sample}}))
    if entity.body_fat_pct is not None:
        points.append(("body-fat", {"dataSource": MANUAL, "bodyFat": {"percentage": float(entity.body_fat_pct),
                                                                       "sampleTime": sample}}))
    return points


def hydration_log(entity) -> list[tuple[str, dict[str, Any]]]:
    end = entity.consumed_at + timedelta(minutes=1)
    return [("hydration-log", {"dataSource": MANUAL, "hydrationLog": {
        "interval": _interval(entity.consumed_at, end, entity.timezone),
        "amountConsumed": {"milliliters": float(entity.amount_ml), "userProvidedUnit": "MILLILITER"}}})]


def _nutrition(start: datetime, end: datetime, zone: str | None, *, name: str | None, meal_type: str | None,
               kcal: Any, protein: Any, carbohydrate: Any, fat: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"interval": _interval(start, end, zone)}
    if name:
        value["foodDisplayName"] = name[:255]
    if meal_type:
        value["mealType"] = meal_type
    if _float(kcal) is not None:
        value["energy"] = {"kcal": _float(kcal)}
    if _float(carbohydrate) is not None:
        value["totalCarbohydrate"] = {"grams": _float(carbohydrate)}
    if _float(fat) is not None:
        value["totalFat"] = {"grams": _float(fat)}
    if _float(protein) is not None:
        value["nutrients"] = [{"nutrient": "PROTEIN", "quantity": {"grams": _float(protein)}}]
    return {"dataSource": MANUAL, "nutritionLog": value}


def nutrition_log(entity) -> list[tuple[str, dict[str, Any]]]:
    end = entity.ended_at or entity.consumed_at + timedelta(minutes=15)
    return [("nutrition-log", _nutrition(entity.consumed_at, end, entity.timezone, name=entity.food_name,
                                         meal_type=entity.meal_type, kcal=entity.energy_kcal, protein=entity.protein_g,
                                         carbohydrate=entity.carbohydrate_g, fat=entity.fat_g))]


def meal(entity) -> list[tuple[str, dict[str, Any]]]:
    """A HercFit meal exports its totals; unknown nutrients are omitted, never sent as 0."""
    return [("nutrition-log", _nutrition(entity.consumed_at, entity.consumed_at + timedelta(minutes=20),
                                         entity.timezone, name=entity.name, meal_type=None, kcal=entity.energy_kcal,
                                         protein=entity.protein_g, carbohydrate=entity.carbohydrate_g,
                                         fat=entity.fat_g))]


def training(entity) -> list[tuple[str, dict[str, Any]]]:
    duration = float(entity.duration_seconds) if entity.duration_seconds else None
    end = entity.ended_at or (entity.started_at + timedelta(seconds=duration) if duration else None)
    if end is None or end <= entity.started_at:
        return []  # no honest interval: nothing to export
    value: dict[str, Any] = {"interval": _interval(entity.started_at, end, entity.timezone),
                             "exerciseType": DISCIPLINE_TYPES.get(entity.discipline, "WORKOUT"),
                             "displayName": entity.name[:255]}
    if duration:
        value["activeDuration"] = f"{int(duration)}s"
    if _float(entity.energy_kcal) is not None:
        value["metricsSummary"] = {"caloriesKcal": _float(entity.energy_kcal)}
    return [("exercise", {"dataSource": MANUAL, "exercise": value})]


def symptom_log(entity) -> list[tuple[str, dict[str, Any]]]:
    return [("symptoms", {"dataSource": MANUAL, "symptoms": {"sampleTime": _sample(entity.recorded_at, entity.timezone),
                                                             "symptoms": list(entity.symptoms)}})]


def mood_log(entity) -> list[tuple[str, dict[str, Any]]]:
    value: dict[str, Any] = {"sampleTime": _sample(entity.recorded_at, entity.timezone)}
    if entity.moods:
        value["moods"] = list(entity.moods)
    if entity.valences:
        value["valences"] = list(entity.valences)
    return [("moods", {"dataSource": MANUAL, "moods": value})]


def menstrual_period_log(entity) -> list[tuple[str, dict[str, Any]]]:
    end = entity.ended_at or entity.started_at + timedelta(days=1)
    value: dict[str, Any] = {"interval": _interval(entity.started_at, end, entity.timezone)}
    if entity.note:
        value["notes"] = entity.note[:1000]
    return [("menstrual-period", {"dataSource": MANUAL, "menstrualPeriod": value})]


def ovulation_test_log(entity) -> list[tuple[str, dict[str, Any]]]:
    return [("ovulation-test", {"dataSource": MANUAL, "ovulationTest": {
        "sampleTime": _sample(entity.recorded_at, entity.timezone), "result": entity.result}})]


BUILDERS = {
    "BodyMetric": body_metric, "HydrationLog": hydration_log, "NutritionLog": nutrition_log, "Meal": meal,
    "Training": training, "SymptomLog": symptom_log, "MoodLog": mood_log, "MenstrualPeriodLog": menstrual_period_log,
    "OvulationTestLog": ovulation_test_log,
}


def build(aggregate_type: str, entity) -> list[tuple[str, dict[str, Any]]]:
    return BUILDERS[aggregate_type](entity)
