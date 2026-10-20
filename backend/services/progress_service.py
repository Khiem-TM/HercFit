"""Aggregate active actual snapshots, including activities outside schedules."""

from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Date, case, func, select

from models.journals import Meal, MealItem, Training, TrainingItem
from models.plans import Plan
from schemas.activity import NUTRIENT_FIELDS
from schemas.progress import DailyProgressRead, MetricProgress, PlanProgressRead, ProgressRead
from schemas.tracking import DateRangeQuery


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


def _metric(row, field, target):
    count = row.get("count", 0)
    known_count = row.get(f"{field}_known", 0)
    known_total = row.get(field) or Decimal(0)
    return MetricProgress(
        target=target, actual=known_total if known_count == count else None,
        known_total=known_total, missing_count=count - known_count,
    )


async def summarize_plan(session, *, user_id, plan_id, start_date=None, end_date=None) -> PlanProgressRead:
    """Compare logs to one explicit historical/current plan in its own timezone."""
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
    """Actual daily totals without inferring any plan targets."""
    return ProgressRead(
        timezone=options.timezone, start_date=options.start_date, end_date=options.end_date,
        days=await _summarize_days(session, user_id, options),
    )


async def _summarize_days(session, user_id, options, plan=None):
    meals = await _daily_totals(session, Meal, user_id, options, NUTRIENT_FIELDS)
    trainings = await _daily_totals(session, Training, user_id, options, ("energy_kcal",))
    days = []
    day = options.start_date
    while day <= options.end_date:
        meal, training = meals.get(day, {}), trainings.get(day, {})
        days.append(DailyProgressRead(
            date=day, meal_count=meal.get("count", 0), training_count=training.get("count", 0),
            calories_in=_metric(meal, "energy_kcal", getattr(plan, "calories_in_kcal", None)),
            exercise_calories=_metric(training, "energy_kcal", getattr(plan, "exercise_calories_kcal", None)),
            calories_out_target=getattr(plan, "calories_out_kcal", None),
            **{field: _metric(meal, field, getattr(plan, field, None)) for field in NUTRIENT_FIELDS if field != "energy_kcal"},
        ))
        day += timedelta(days=1)
    return days
