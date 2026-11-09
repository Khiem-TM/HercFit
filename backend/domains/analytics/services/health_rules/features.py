"""Gom Features và Profile của một người dùng từ các service sẵn có (đọc, không ghi, không cache)."""
from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from domains.analytics.services.health_rules.evaluate import DayHealth, DayIntake, Features, Profile
from domains.health_records import views
from domains.health_records.schemas.health import recommended_sleep_hours
from domains.nutrition.services.nutrition_targets import COMPLETE_DAY_MIN_MEALS

HEALTH_DAYS = 14
INTAKE_DAYS = 8
TRAINED_LEVELS = {"INTERMEDIATE", "ADVANCED"}
ACTIVE_LEVELS = {"active", "very_active"}


def _float(value) -> float | None:
    return float(value) if value is not None else None


def intake_days(rows: dict, today: date) -> dict[date, DayIntake]:
    """Ngày đã trọn (trước hôm nay) có ít nhất 2 bữa và đủ năng lượng của mọi bữa thì là ngày đủ bữa."""
    found = {}
    for day, row in rows.items():
        count = row.get("count", 0)

        def known(field: str) -> float | None:
            return _float(row.get(field)) if row.get(f"{field}_known", 0) == count and count else None

        kcal = known("energy_kcal")
        found[day] = DayIntake(meals=count, complete=day < today and count >= COMPLETE_DAY_MIN_MEALS and kcal is not None,
                               kcal=kcal, protein_g=known("protein_g"), fat_g=known("fat_g"), fiber_g=known("fiber_g"))
    return found


async def gather(session, user, today: date, zone: str) -> tuple[Features, Profile]:
    from domains.analytics.services.progress_service import daily_meal_totals
    from domains.body.models.body_metrics import BodyMetric
    from domains.nutrition.services.nutrition_targets import NutritionTargetService
    from domains.shared.schemas.tracking import DateRangeQuery

    targets = await NutritionTargetService(session, user).targets(timezone=zone, today=today)
    inputs = targets.inputs
    daily = await views.daily(session, user.id, today - timedelta(days=HEALTH_DAYS), today, zone)
    out = await views.energy_out(session, user.id, today - timedelta(days=INTAKE_DAYS), today - timedelta(days=1), zone)
    health = {row.local_date: DayHealth(
        rhr=_float(row.resting_hr_bpm), spo2=_float(row.spo2_avg_pct), sleep_minutes=row.sleep_minutes,
        steps=row.steps, active_zone_minutes=row.active_zone_minutes, energy_out=out.get(row.local_date))
        for row in daily}
    rows = await daily_meal_totals(session, user.id, DateRangeQuery(
        start_date=today - timedelta(days=INTAKE_DAYS), end_date=today, timezone=zone))
    waist = await BodyMetric.latest(session, user.id, "waist_cm")
    features = Features(
        today=today, health=health, intake=intake_days(rows, today),
        weights=[(point.date, float(point.weight_kg)) for point in targets.weight_trend],
        waist=(waist.recorded_at.astimezone(ZoneInfo(zone)).date(), float(waist.waist_cm)) if waist is not None else None,
    )
    training = ((user.personal_info or {}).get("training") or {}).get("experience_level")
    age = inputs.age
    profile = Profile(
        sex=inputs.sex, age=age, height_cm=_float(inputs.height_cm), goal=inputs.goal_type,
        trained=training in TRAINED_LEVELS or inputs.activity_level in ACTIVE_LEVELS,
        bmr_kcal=_float(targets.bmr_kcal), target_kcal=_float(targets.target_kcal),
        protein_target_g=_float(targets.macros.protein_g) if targets.macros else None,
        recommended_sleep=recommended_sleep_hours(age),
    )
    return features, profile
