"""Assemble a user's energy targets from stored profile, measurements, goal and logs."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from models.body_metrics import BodyMetric
from models.goal import Goal
from models.journals import Meal
from schemas.activity import NUTRIENT_FIELDS
from schemas.nutrition import NutritionTargetsRead
from schemas.tracking import DateRangeQuery
from services import energy
from services.common import UserService

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
        from services.progress_service import daily_meal_totals

        tz = ZoneInfo(timezone)
        today = today or datetime.now(tz).date()
        user = self.user
        metrics = await BodyMetric.list_for_user(
            self.session, user_id=self.user_id,
            recorded_from=datetime.combine(today - timedelta(days=90), datetime.min.time(), tz), limit=200,
        )
        weights = [(m.recorded_at.astimezone(tz).date(), float(m.weight_kg)) for m in metrics if m.weight_kg is not None]
        height = next((float(m.height_cm) for m in metrics if m.height_cm is not None), None)
        if height is None:
            row = (await self.session.execute(
                select(BodyMetric.height_cm).where(BodyMetric.user_id == self.user_id, BodyMetric.is_active.is_(True),
                                                   BodyMetric.height_cm.is_not(None))
                .order_by(BodyMetric.recorded_at.desc()).limit(1)
            )).scalar_one_or_none()
            height = float(row) if row is not None else None
        latest_weight = weights[0][1] if weights else None
        if latest_weight is None:
            latest = await BodyMetric.get_latest_for_user(self.session, user_id=self.user_id)
            latest_weight = float(latest.weight_kg) if latest is not None and latest.weight_kg is not None else None

        trend = energy.trend_series(weights)
        # Plan from the smoothed weight so one salty dinner does not move the target.
        planning_weight = trend[-1][2] if trend else latest_weight
        goal_type, target_weight, target_date = _goal_inputs(await Goal.get_current_for_user(self.session, user_id=self.user_id))
        activity = ((user.personal_info or {}).get("activity") or {}).get("level")
        inputs = energy.EnergyInputs(
            weight_kg=planning_weight, height_cm=height, age=user.age, sex=getattr(user, "sex", None),
            activity_level=activity, goal_type=goal_type, target_weight_kg=target_weight,
            target_date=target_date, today=today,
        )
        result = energy.energy_targets(inputs)

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
        adaptive = energy.adaptive_expenditure(intakes, weights, end=today)

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
            warnings=result.warnings, method=energy.METHOD,
        )
