"""Deterministic energy and macro targets. Pure functions: no I/O, no ORM.

Every result carries the method and the inputs it used so a reader (or the
agent) can reproduce it instead of letting a language model do arithmetic.

References
- Mifflin MD, St Jeor ST et al. (1990) resting energy equation; Frankenfield et al.
  (2005, J Am Diet Assoc) found it the most often within 10% of measured RMR.
- Activity multipliers 1.2–1.9 (commonly used physical activity factors).
- ~7,700 kcal per kg of body-mass change (a planning approximation, not a law).
- Jäger et al. (2017) ISSN Position Stand: 1.4–2.0 g protein/kg/day for most
  exercising individuals.
- Fat 20–35% of energy (acceptable macronutrient distribution range); 25% used.
- Fibre 14 g per 1,000 kcal (US Dietary Guidelines adequacy benchmark).
- Weight trend: exponentially smoothed moving average (10% per day), as in
  Walker's "The Hacker's Diet", to separate fat-mass change from water noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import fmean
from typing import Literal

ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
GoalType = Literal["fat_loss", "muscle_gain", "maintenance", "fitness"]

ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9,
}
KCAL_PER_KG = 7700.0
# Unsupervised intake floors often used in weight-management guidance.
SEX_FLOOR_KCAL = {"FEMALE": 1200.0, "MALE": 1500.0, None: 1350.0}
MAX_LOSS_FRACTION_PER_WEEK = 0.01      # never plan to lose more than 1% of body weight per week
DEFAULT_LOSS_FRACTION_PER_WEEK = 0.005  # 0.5% per week when no target date is set
GAIN_SURPLUS_FRACTION, GAIN_SURPLUS_CAP_KCAL = 0.10, 400.0
PROTEIN_G_PER_KG = {"fat_loss": 1.8, "muscle_gain": 1.8, "fitness": 1.6, "maintenance": 1.4}
SEDENTARY_PROTEIN_G_PER_KG = 1.0
FAT_ENERGY_FRACTION = 0.25
FIBER_G_PER_1000_KCAL = 14.0
TREND_ALPHA = 0.1

METHOD = {
    "bmr": "Mifflin-St Jeor: 10×kg + 6.25×cm − 5×tuổi + 5 (nam) hoặc − 161 (nữ)",
    "tdee": "BMR × hệ số vận động (1.2–1.9)",
    "target": "TDEE ± điều chỉnh theo mục tiêu; giảm cân tối đa 1% cân nặng/tuần, không thấp hơn max(BMR, sàn theo giới)",
    "macros": "Protein theo g/kg (ISSN 2017: 1.4–2.0 g/kg cho người tập), chất béo 25% năng lượng, carb phần còn lại, chất xơ 14 g/1000 kcal",
    "trend": "Cân nặng xu hướng: trung bình trượt hàm mũ 10%/ngày",
    "adaptive": "Chi tiêu ≈ năng lượng ăn trung bình − (thay đổi cân xu hướng × 7700 kcal/kg) / số ngày",
}


def mifflin_st_jeor(weight_kg: float, height_cm: float, age: int, sex: str | None) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "MALE":
        return base + 5
    if sex == "FEMALE":
        return base - 161
    return base - 78  # midpoint of the two constants when sex is not provided


@dataclass
class EnergyInputs:
    weight_kg: float | None
    height_cm: float | None
    age: int | None
    sex: str | None = None
    activity_level: str | None = None
    goal_type: str | None = None
    target_weight_kg: float | None = None
    target_date: date | None = None
    today: date | None = None


@dataclass
class EnergyTargets:
    status: Literal["ok", "incomplete_profile"]
    missing: list[str] = field(default_factory=list)
    bmr_kcal: float | None = None
    tdee_kcal: float | None = None
    target_kcal: float | None = None
    weekly_change_kg: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carbohydrate_g: float | None = None
    fiber_g: float | None = None
    protein_g_per_kg: float | None = None
    activity_factor: float | None = None
    goal_type: str = "maintenance"
    warnings: list[str] = field(default_factory=list)


def energy_targets(inputs: EnergyInputs) -> EnergyTargets:
    missing = [name for name, value in (("weight_kg", inputs.weight_kg), ("height_cm", inputs.height_cm),
                                        ("age", inputs.age)) if value is None]
    goal = inputs.goal_type if inputs.goal_type in PROTEIN_G_PER_KG else "maintenance"
    if missing:
        return EnergyTargets(status="incomplete_profile", missing=missing, goal_type=goal)
    weight, height, age = float(inputs.weight_kg), float(inputs.height_cm), int(inputs.age)
    warnings: list[str] = []
    if inputs.sex not in ("MALE", "FEMALE"):
        warnings.append("sex_unknown_used_average_constant")
    level = inputs.activity_level if inputs.activity_level in ACTIVITY_FACTORS else "sedentary"
    if inputs.activity_level not in ACTIVITY_FACTORS:
        warnings.append("activity_unknown_assumed_sedentary")
    factor = ACTIVITY_FACTORS[level]
    bmr = mifflin_st_jeor(weight, height, age, inputs.sex)
    tdee = bmr * factor
    target, weekly = tdee, 0.0

    if age < 18:
        # Growth needs energy; no deficit or surplus is planned for minors.
        warnings.append("minor_maintenance_only")
        goal_effective = "maintenance"
    else:
        goal_effective = goal
    if goal_effective == "fat_loss":
        rate = weight * DEFAULT_LOSS_FRACTION_PER_WEEK
        today, deadline = inputs.today, inputs.target_date
        if inputs.target_weight_kg is not None and deadline and today and deadline > today:
            weeks = (deadline - today).days / 7
            needed = (weight - float(inputs.target_weight_kg)) / weeks if weeks > 0 else 0.0
            if needed <= 0:
                warnings.append("target_weight_already_reached")
                rate = 0.0
            else:
                rate = needed
        if rate > weight * MAX_LOSS_FRACTION_PER_WEEK:
            warnings.append("target_date_too_aggressive_rate_capped")
            rate = weight * MAX_LOSS_FRACTION_PER_WEEK
        target = tdee - rate * KCAL_PER_KG / 7
        floor = max(SEX_FLOOR_KCAL.get(inputs.sex, SEX_FLOOR_KCAL[None]), bmr)
        if target < floor:
            warnings.append("intake_floor_applied")
            target = floor
        weekly = -(tdee - target) * 7 / KCAL_PER_KG
    elif goal_effective == "muscle_gain":
        surplus = min(tdee * GAIN_SURPLUS_FRACTION, GAIN_SURPLUS_CAP_KCAL)
        target = tdee + surplus
        weekly = surplus * 7 / KCAL_PER_KG

    per_kg = SEDENTARY_PROTEIN_G_PER_KG if (goal_effective == "maintenance" and level == "sedentary") \
        else PROTEIN_G_PER_KG[goal_effective]
    protein = per_kg * weight
    fat = target * FAT_ENERGY_FRACTION / 9
    carbs = max(0.0, (target - protein * 4 - fat * 9) / 4)
    if carbs == 0.0:
        warnings.append("protein_and_fat_exceed_target_energy")
    fiber = target / 1000 * FIBER_G_PER_1000_KCAL
    r = lambda value, digits=0: round(value, digits)
    return EnergyTargets(
        status="ok", bmr_kcal=r(bmr), tdee_kcal=r(tdee), target_kcal=r(target), weekly_change_kg=r(weekly, 2),
        protein_g=r(protein), fat_g=r(fat), carbohydrate_g=r(carbs), fiber_g=r(fiber),
        protein_g_per_kg=per_kg, activity_factor=factor, goal_type=goal_effective, warnings=warnings,
    )


def trend_series(points: list[tuple[date, float]], alpha: float = TREND_ALPHA) -> list[tuple[date, float, float]]:
    """(day, measured, trend). Same-day readings are averaged; gaps decay by the
    number of days elapsed so a sparse logger is not over-smoothed."""
    by_day: dict[date, list[float]] = {}
    for day, weight in points:
        by_day.setdefault(day, []).append(float(weight))
    series: list[tuple[date, float, float]] = []
    trend = None
    previous = None
    for day in sorted(by_day):
        measured = fmean(by_day[day])
        if trend is None:
            trend = measured
        else:
            gap = max(1, (day - previous).days)
            weight_of_new = 1 - (1 - alpha) ** gap
            trend = trend + weight_of_new * (measured - trend)
        series.append((day, measured, round(trend, 3)))
        previous = day
    return series


@dataclass
class AdaptiveExpenditure:
    status: Literal["ok", "insufficient_data"]
    expenditure_kcal: float | None = None
    average_intake_kcal: float | None = None
    trend_change_kg: float | None = None
    span_days: int = 0
    complete_intake_days: int = 0
    weight_points: int = 0
    reasons: list[str] = field(default_factory=list)


def adaptive_expenditure(intakes: list[tuple[date, float | None, bool]], weights: list[tuple[date, float]],
                         end: date, window_days: int = 28, min_span_days: int = 14,
                         min_complete_days: int = 10, min_weight_points: int = 4) -> AdaptiveExpenditure:
    """Energy-balance estimate of actual expenditure from logged intake and trend weight.

    intakes: (day, kcal or None, complete) where complete means the whole day was logged.
    """
    from datetime import timedelta

    start = end - timedelta(days=window_days - 1)
    series = [row for row in trend_series([p for p in weights if p[0] <= end]) if row[0] >= start]
    complete = [kcal for day, kcal, done in intakes if start <= day <= end and done and kcal is not None]
    span = (series[-1][0] - series[0][0]).days if len(series) >= 2 else 0
    reasons = []
    if len(series) < min_weight_points:
        reasons.append(f"need_{min_weight_points}_weigh_ins_in_window")
    if span < min_span_days:
        reasons.append(f"need_{min_span_days}_days_between_weigh_ins")
    if len(complete) < min_complete_days:
        reasons.append(f"need_{min_complete_days}_fully_logged_days")
    result = AdaptiveExpenditure(status="insufficient_data", span_days=span, complete_intake_days=len(complete),
                                 weight_points=len(series), reasons=reasons)
    if reasons:
        return result
    average = fmean(complete)
    change = series[-1][2] - series[0][2]
    result.status, result.reasons = "ok", []
    result.average_intake_kcal = round(average)
    result.trend_change_kg = round(change, 2)
    result.expenditure_kcal = round(average - change * KCAL_PER_KG / span)
    return result
