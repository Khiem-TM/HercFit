"""Tổng hợp các ảnh chụp thực tế đang hoạt động, kể cả hoạt động ngoài lịch."""

from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Date, case, func, select

from domains.nutrition.models.meals import Meal, MealItem
from domains.training.models.trainings import Training, TrainingItem
from domains.goals_plans.models.plans import Plan
from domains.shared.schemas.activity import NUTRIENT_FIELDS
from domains.analytics.schemas.progress import DailyProgressRead, MetricProgress, PlanProgressRead, ProgressRead
from domains.shared.schemas.tracking import DateRangeQuery


async def _daily_totals(session, model, user_id, options, fields):
    lower, upper = options.utc_bounds()
    timestamp = getattr(model, model.TIME_FIELD)
    day = func.timezone(options.timezone, timestamp).cast(Date).label("day")
    columns = [day, func.count().label("count")]
    item_model, parent_key = (MealItem, MealItem.meal_id) if model is Meal else (TrainingItem, TrainingItem.training_id)
    for field in fields:
        column = getattr(model, field)
        item_sum = select(func.sum(getattr(item_model, field))).where(parent_key == model.id).correlate(model).scalar_subquery()
        known = case((model.detail_status == "AGGREGATE_ONLY", column), else_=item_sum)
        columns.extend((func.sum(known).label(field), func.count(column).label(f"{field}_known")))
    rows = (await session.execute(
        select(*columns).where(model.user_id == user_id, model.is_active.is_(True), timestamp >= lower, timestamp < upper).group_by(day)
    )).mappings().all()
    return {row["day"]: row for row in rows}


async def daily_meal_totals(session, user_id, options: DateRangeQuery):
    """Theo từng ngày địa phương: số bữa, tổng dinh dưỡng đã biết và số bữa có từng giá trị.

    Bộ đọc v2 `nutrition`: bữa ghi ở ứng dụng khác và nhập về từ Google Health
    (nhật ký dinh dưỡng không gắn với bữa HercFit) cũng được tính là bữa ăn; giá trị chúng thiếu
    vẫn là chưa biết cho ngày đó. Dữ liệu HercFit tự xuất không bao giờ được nhập ngược lại.
    """
    totals = await _daily_totals(session, Meal, user_id, options, NUTRIENT_FIELDS)
    from core.flags import reader_v2
    from domains.identity import consent

    if not reader_v2("nutrition") or not await consent.device_access(session, user_id):
        return totals
    external = await _external_meal_totals(session, user_id, options)
    merged = {}
    for day in totals.keys() | external.keys():
        mine, theirs = totals.get(day) or {}, external.get(day) or {}
        row = {"count": mine.get("count", 0) + theirs.get("count", 0)}
        for field in NUTRIENT_FIELDS:
            parts = [Decimal(str(value)) for value in (mine.get(field), theirs.get(field)) if value is not None]
            row[field] = sum(parts, Decimal(0)) if parts else None
            row[f"{field}_known"] = mine.get(f"{field}_known", 0) + theirs.get(f"{field}_known", 0)
        merged[day] = row
    return merged


async def _external_meal_totals(session, user_id, options: DateRangeQuery):
    from domains.nutrition.models.logs import NutritionLog

    lower, upper = options.utc_bounds()
    day = func.timezone(options.timezone, NutritionLog.consumed_at).cast(Date).label("day")
    fiber = NutritionLog.nutrients["DIETARY_FIBER"].as_float()
    values = {"energy_kcal": NutritionLog.energy_kcal, "protein_g": NutritionLog.protein_g,
              "carbohydrate_g": NutritionLog.carbohydrate_g, "fat_g": NutritionLog.fat_g, "fiber_g": fiber}
    columns = [day, func.count().label("count")]
    for field in NUTRIENT_FIELDS:
        columns.extend((func.sum(values[field]).label(field), func.count(values[field]).label(f"{field}_known")))
    rows = (await session.execute(select(*columns).where(
        NutritionLog.user_id == user_id, NutritionLog.is_active.is_(True), NutritionLog.source == "GOOGLE_HEALTH",
        NutritionLog.meal_id.is_(None), NutritionLog.consumed_at >= lower, NutritionLog.consumed_at < upper,
    ).group_by(day))).mappings().all()
    return {row["day"]: row for row in rows}


def _metric(row, field, target):
    count = row.get("count", 0)
    known_count = row.get(f"{field}_known", 0)
    known_total = row.get(field) or Decimal(0)
    return MetricProgress(
        target=target, actual=known_total if known_count == count else None,
        known_total=known_total, missing_count=count - known_count,
    )


async def summarize_plan(session, *, user_id, plan_id, start_date=None, end_date=None) -> PlanProgressRead:
    """So sánh nhật ký với một kế hoạch tường minh trong quá khứ/hiện tại theo múi giờ riêng của nó."""
    plan = await Plan.get_for_user(session, plan_id, user_id=user_id)
    if plan is None:
        raise HTTPException(404, "Plan not found")
    options = DateRangeQuery(
        start_date=start_date or plan.start_date, end_date=end_date or plan.end_date, timezone=plan.timezone,
    )
    if options.start_date < plan.start_date or options.end_date > plan.end_date:
        raise HTTPException(422, "Progress dates must be within the plan")
    days = await _summarize_days(session, user_id, options, plan)
    return PlanProgressRead(
        plan_id=plan.id, timezone=plan.timezone, start_date=options.start_date, end_date=options.end_date, days=days,
    )


async def summarize_user(session, *, user_id, options: DateRangeQuery) -> ProgressRead:
    """Tổng thực tế theo ngày mà không suy ra chỉ tiêu kế hoạch nào."""
    return ProgressRead(
        timezone=options.timezone, start_date=options.start_date, end_date=options.end_date,
        days=await _summarize_days(session, user_id, options),
    )


async def _summarize_days(session, user_id, options, plan=None):
    from domains.health_records.services.health_service import daily_expenditure
    from domains.training.services.training_analytics import daily_loads

    expenditure = await daily_expenditure(session, user_id, options.start_date, options.end_date)
    meals = await daily_meal_totals(session, user_id, options)
    trainings = await _daily_totals(session, Training, user_id, options, ("energy_kcal",))
    loads, _missing = await daily_loads(session, user_id, options.start_date, options.end_date, options.timezone)
    days = []
    day = options.start_date
    while day <= options.end_date:
        meal, training = meals.get(day, {}), trainings.get(day, {})
        days.append(DailyProgressRead(
            date=day, meal_count=meal.get("count", 0), training_count=training.get("count", 0),
            calories_in=_metric(meal, "energy_kcal", getattr(plan, "calories_in_kcal", None)),
            exercise_calories=_metric(training, "energy_kcal", getattr(plan, "exercise_calories_kcal", None)),
            calories_out_target=getattr(plan, "calories_out_kcal", None),
            calories_out_actual=expenditure.get(day),
            training_load=loads.get(day, Decimal(0)),
            **{field: _metric(meal, field, getattr(plan, field, None)) for field in NUTRIENT_FIELDS if field != "energy_kcal"},
        ))
        day += timedelta(days=1)
    return days
