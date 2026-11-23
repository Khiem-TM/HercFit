"""Service nghiệp vụ của miền dinh dưỡng."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Literal
from zoneinfo import ZoneInfo

from domains.body import services as readings
from domains.body.models import BodyMetric
from domains.goals_plans.models import Goal
from domains.health_records.services import device_expenditure, observed_activity_level
from domains.nutrition.schemas import NutritionTargetsRead
from domains.shared.schemas import DateRangeQuery
from domains.shared.services import UserService

# --------------------------------------------------------------------------------------------------
# Mục tiêu năng lượng và macro tất định. Hàm thuần: không I/O, không ORM.
#
# Mỗi kết quả mang theo phương pháp và đầu vào đã dùng để người đọc (hoặc
# agent) tái tạo được, thay vì để mô hình ngôn ngữ làm tính toán.
#
# Tài liệu tham khảo
# - Mifflin MD, St Jeor ST và cộng sự (1990) phương trình năng lượng nghỉ; Frankenfield và cộng sự
#   (2005, J Am Diet Assoc) thấy nó thường nằm trong 10% so với RMR đo được nhất.
# - Hệ số vận động 1.2–1.9 (các hệ số hoạt động thể chất thường dùng).
# - ~7.700 kcal cho mỗi kg thay đổi khối lượng cơ thể (xấp xỉ để lập kế hoạch, không phải định luật).
# - Jäger và cộng sự (2017) ISSN Position Stand: 1.4–2.0 g protein/kg/ngày cho đa số
#   người tập luyện.
# - Chất béo 20–35% năng lượng (khoảng phân bố macro chấp nhận được); dùng 25%.
# - Chất xơ 14 g mỗi 1.000 kcal (mốc đủ của Hướng dẫn Dinh dưỡng Hoa Kỳ).
# - Xu hướng cân nặng: trung bình trượt làm trơn mũ (10% mỗi ngày), như trong
#   "The Hacker's Diet" của Walker, để tách thay đổi khối mỡ khỏi nhiễu nước.
# --------------------------------------------------------------------------------------------------

ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9,
}
KCAL_PER_KG = 7700.0
# Ngưỡng sàn lượng ăn không giám sát thường dùng trong hướng dẫn kiểm soát cân nặng.
SEX_FLOOR_KCAL = {"FEMALE": 1200.0, "MALE": 1500.0, None: 1350.0}
MAX_LOSS_FRACTION_PER_WEEK = 0.01      # không bao giờ lên kế hoạch giảm quá 1% cân nặng mỗi tuần
DEFAULT_LOSS_FRACTION_PER_WEEK = 0.005  # 0,5% mỗi tuần khi chưa đặt ngày đạt mục tiêu
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
    return base - 78  # điểm giữa của hai hằng số khi không có giới tính


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
        # Tăng trưởng cần năng lượng; không lập kế hoạch thâm hụt hay dư thừa cho người chưa thành niên.
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
    def r(value, digits=0):
        return round(value, digits)
    return EnergyTargets(
        status="ok", bmr_kcal=r(bmr), tdee_kcal=r(tdee), target_kcal=r(target), weekly_change_kg=r(weekly, 2),
        protein_g=r(protein), fat_g=r(fat), carbohydrate_g=r(carbs), fiber_g=r(fiber),
        protein_g_per_kg=per_kg, activity_factor=factor, goal_type=goal_effective, warnings=warnings,
    )


def trend_series(points: list[tuple[date, float]], alpha: float = TREND_ALPHA) -> list[tuple[date, float, float]]:
    """(ngày, số đo, xu hướng). Số đo cùng ngày được lấy trung bình; khoảng trống suy giảm theo
    số ngày đã trôi qua để người ghi thưa không bị làm trơn quá mức."""
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
    """Ước tính mức tiêu hao thực tế theo cân bằng năng lượng từ lượng ăn đã ghi và cân nặng xu hướng.

    intakes: (ngày, kcal hoặc None, complete) trong đó complete nghĩa là cả ngày đã được ghi.
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


# --------------------------------------------------------------------------------------------------
# Tập hợp mục tiêu năng lượng của người dùng từ hồ sơ, số đo, mục tiêu và nhật ký đã lưu.
# --------------------------------------------------------------------------------------------------

GOAL_TYPES = {"fat_loss", "muscle_gain", "maintenance", "fitness"}
COMPLETE_DAY_MIN_MEALS = 2


def _goal_inputs(goal: Goal | None) -> tuple[str | None, float | None, date | None]:
    if goal is None:
        return None, None, None
    goal_type = next((g for g in goal.goal_types or [] if g in GOAL_TYPES), None)
    target = goal.weight_kg_target
    if target is None:
        weight_target = (goal.targets or {}).get("weight_kg") or {}
        if weight_target.get("operator") == "eq" and isinstance(weight_target.get("value"), (int, float)):
            target = weight_target["value"]
    return goal_type, (float(target) if target is not None else None), goal.target_date


class NutritionTargetService(UserService):
    async def targets(self, *, timezone: str = "Asia/Ho_Chi_Minh", today: date | None = None) -> NutritionTargetsRead:
        from domains.analytics.services import daily_meal_totals

        tz = ZoneInfo(timezone)
        today = today or datetime.now(tz).date()
        user = self.user
        metrics = await BodyMetric.list_for_user(
            self.session, user_id=self.user_id,
            recorded_from=datetime.combine(today - timedelta(days=90), datetime.min.time(), tz), limit=200,
        )
        weights = [(m.recorded_at.astimezone(tz).date(), float(m.weight_kg)) for m in readings.distinct_weighins(metrics)]
        height = next((float(m.height_cm) for m in metrics if m.height_cm is not None), None)
        if height is None:
            row = await BodyMetric.latest(self.session, self.user_id, "height_cm")
            height = float(row.height_cm) if row is not None else None
        latest_weight = weights[0][1] if weights else None
        if latest_weight is None:
            latest = await BodyMetric.get_latest_for_user(self.session, user_id=self.user_id)
            latest_weight = float(latest.weight_kg) if latest is not None and latest.weight_kg is not None else None

        trend = trend_series(weights)
        # Lập kế hoạch từ cân nặng đã làm trơn để một bữa tối mặn không làm dịch chỉ tiêu.
        planning_weight = trend[-1][2] if trend else latest_weight
        goal_type, target_weight, target_date = _goal_inputs(await Goal.get_current_for_user(self.session, user_id=self.user_id))
        activity = ((user.personal_info or {}).get("activity") or {}).get("level")
        activity_source = "declared" if activity else None
        if not activity:
            # Khai báo còn thiếu được điền từ 28 ngày bước chân của thiết bị.
            activity = await observed_activity_level(self.session, self.user_id, today)
            activity_source = "observed" if activity else None
        inputs = EnergyInputs(
            weight_kg=planning_weight, height_cm=height, age=user.age, sex=getattr(user, "sex", None),
            activity_level=activity, goal_type=goal_type, target_weight_kg=target_weight,
            target_date=target_date, today=today,
        )
        result = energy_targets(inputs)

        window = DateRangeQuery(start_date=today - timedelta(days=27), end_date=today, timezone=timezone)
        rows = await daily_meal_totals(self.session, self.user_id, window)
        intakes = []
        for day_offset in range(28):
            day = window.start_date + timedelta(days=day_offset)
            row = rows.get(day) or {}
            count = row.get("count", 0)
            known = row.get("energy_kcal_known", 0)
            kcal = float(row["energy_kcal"]) if row.get("energy_kcal") is not None else None
            complete = day < today and count >= COMPLETE_DAY_MIN_MEALS and known == count
            intakes.append((day, kcal, complete))
        adaptive = adaptive_expenditure(intakes, weights, end=today)

        today_row = rows.get(today) or {}
        consumed = float(today_row.get("energy_kcal") or 0)
        today_info = {
            "date": today, "meal_count": today_row.get("count", 0), "energy_kcal": round(consumed),
            "protein_g": round(float(today_row.get("protein_g") or 0)),
            "missing_values": today_row.get("count", 0) - today_row.get("energy_kcal_known", 0),
            "remaining_kcal": round(result.target_kcal - consumed) if result.target_kcal is not None else None,
        }
        macros = None
        if result.status == "ok":
            macros = {"protein_g": result.protein_g, "fat_g": result.fat_g, "carbohydrate_g": result.carbohydrate_g,
                      "fiber_g": result.fiber_g, "protein_g_per_kg": result.protein_g_per_kg}
        return NutritionTargetsRead(
            status=result.status, missing=result.missing,
            inputs={"weight_kg": planning_weight, "height_cm": height, "age": user.age, "sex": getattr(user, "sex", None),
                    "activity_level": activity, "goal_type": goal_type, "target_weight_kg": target_weight,
                    "target_date": target_date, "trend_weight_kg": trend[-1][2] if trend else None},
            bmr_kcal=result.bmr_kcal, tdee_kcal=result.tdee_kcal, target_kcal=result.target_kcal,
            weekly_change_kg=result.weekly_change_kg, goal_type=result.goal_type,
            activity_factor=result.activity_factor, macros=macros,
            adaptive=adaptive.__dict__, today=today_info,
            weight_trend=[{"date": d, "weight_kg": w, "trend_kg": t} for d, w, t in trend[-30:]],
            warnings=result.warnings, method=METHOD, activity_level_source=activity_source,
            device_expenditure_kcal=await device_expenditure(self.session, self.user_id, today),
        )
