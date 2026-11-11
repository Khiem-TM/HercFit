"""Quyền đọc dữ liệu sức khoẻ đã đồng bộ (health_points qua views) và hồ sơ sức khoẻ suy ra."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Request

from domains.body.models.body_metrics import BodyMetric
from domains.body.services import readings
from domains.health_records import ports, views
from domains.health_records.types import spec
from domains.identity import consent
from domains.health_records.schemas.health import (
    WORN_DAY_MIN_STEPS,
    HealthOverviewQuery,
    HealthOverviewRead,
    HealthProfileRead,
    HealthSampleQuery,
    activity_level_from_steps,
)
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, DateRangeQuery
from domains.shared.services.common import UserService
from domains.analytics.services.health_profile import MIN_WORN_DAYS_FOR_LEVEL, build_overview, build_profile

from core.principal import AGENT_CLIENT_HEADER  # noqa: E402,F401  (re-export cho các import cũ)
COMPLETE_DAY_MIN_MEALS = 2
# Loại mẫu mà registry đánh dấu nhạy cảm (types.DataType.sensitive), theo tên sample_type của API.
SENSITIVE_SAMPLES = frozenset(sample for data_type, (sample, *_rest) in views.SAMPLES.items()
                              if spec(data_type).sensitive)


async def measured_resting_hr(session, user_id, today: date) -> int | None:
    """Trung vị nhịp tim nghỉ từ thiết bị trong 7 ngày gần nhất (None khi bên đọc không có quyền)."""
    if not await consent.device_access(session, user_id):
        return None
    values = sorted(row.resting_hr_bpm for row in await views.daily(session, user_id, today - timedelta(days=6), today)
                    if row.resting_hr_bpm is not None)
    return values[len(values) // 2] if values else None


async def observed_activity_level(session, user_id, today: date) -> str | None:
    """Mức vận động theo bước chân trên 28 ngày có đeo; None khi có ít hơn 7 ngày đeo."""
    if not await consent.device_access(session, user_id):
        return None
    steps = [row.steps for row in await views.daily(session, user_id, today - timedelta(days=27), today)
             if row.steps is not None and row.steps >= WORN_DAY_MIN_STEPS]
    return activity_level_from_steps(sum(steps) / len(steps)) if len(steps) >= MIN_WORN_DAYS_FOR_LEVEL else None


async def device_expenditure(session, user_id, today: date, days: int = 14) -> float | None:
    """Trung bình tổng năng lượng tiêu hao trên các ngày có đeo đã trọn (trong quá khứ)."""
    if not await consent.device_access(session, user_id):
        return None
    start, end = today - timedelta(days=days), today - timedelta(days=1)
    worn = {row.local_date for row in await views.daily(session, user_id, start, end)
            if row.steps is not None and row.steps >= WORN_DAY_MIN_STEPS}
    values = [kcal for day, kcal in (await views.energy_out(session, user_id, start, end)).items() if day in worn]
    return round(sum(values) / len(values)) if len(values) >= 3 else None


async def daily_expenditure(session, user_id, start: date, end: date, zone: str = DEFAULT_TIMEZONE) -> dict[date, float]:
    if not await consent.device_access(session, user_id):
        return {}
    return await views.energy_out(session, user_id, start, end, zone)


class HealthService(UserService):
    async def connection(self) -> ports.ProviderStatus | None:
        return await ports.provider_status(self.session, self.user_id)

    async def require_assistant_access(self, request: Request | None = None) -> None:
        """Trợ lý chỉ đọc dữ liệu thiết bị khi người dùng cho phép (identity.consent)."""
        await consent.require_device_access(self.session, self.user_id)

    def _today(self, zone: str) -> date:
        return datetime.now(ZoneInfo(zone)).date()

    async def profile(self, timezone: str = DEFAULT_TIMEZONE, today: date | None = None) -> HealthProfileRead:
        today = today or self._today(timezone)
        connection = await self.connection()
        metrics = await BodyMetric.list_for_user(self.session, user_id=self.user_id, limit=200)
        daily = await views.daily(self.session, self.user_id, today - timedelta(days=27), today, timezone)
        return build_profile(today=today, zone=timezone, user=self.user, metrics=metrics, daily=daily,
                             connection=connection)

    async def overview(self, query: HealthOverviewQuery) -> HealthOverviewRead:
        from domains.analytics.services.progress_service import daily_meal_totals

        end = query.end_date or self._today(query.timezone)
        start = end - timedelta(days=query.days - 1)
        connection = await self.connection()
        daily = await views.daily(self.session, self.user_id, start, end, query.timezone)
        sleep = await views.sleep(self.session, self.user_id, start, end)
        workouts = await views.workouts(self.session, self.user_id, start, end)
        rows = await daily_meal_totals(self.session, self.user_id,
                                       DateRangeQuery(start_date=start, end_date=end, timezone=query.timezone))
        intake = {day: float(row["energy_kcal"]) for day, row in rows.items()
                  if row.get("energy_kcal") is not None and row["count"] >= COMPLETE_DAY_MIN_MEALS
                  and row.get("energy_kcal_known") == row["count"]}
        lower = datetime.combine(start, datetime.min.time(), ZoneInfo(query.timezone))
        metrics = await BodyMetric.list_for_user(self.session, user_id=self.user_id, recorded_from=lower, limit=200)
        weights = sorted((m.recorded_at.astimezone(ZoneInfo(query.timezone)).date(), float(m.weight_kg))
                         for m in readings.distinct_weighins(metrics))
        age = self.user.age if self.user.age is not None else (
            (connection.provider_profile or {}).get("age") if connection is not None else None)
        return build_overview(start=start, end=end, zone=query.timezone,
                              connected=connection is not None and connection.connected,
                              age=age, daily=daily, sleep=sleep, workouts=workouts, intake=intake, weights=weights,
                              energy_out=await views.energy_out(self.session, self.user_id, start, end, query.timezone))

    async def daily(self, query: DateRangeQuery):
        rows = await views.daily(self.session, self.user_id, query.start_date, query.end_date, query.timezone)
        return rows[query.offset:query.offset + query.limit]

    async def sleep(self, query: DateRangeQuery):
        rows = await views.sleep(self.session, self.user_id, query.start_date, query.end_date)
        return rows[query.offset:query.offset + query.limit]

    async def workouts(self, query: DateRangeQuery):
        rows = await views.workouts(self.session, self.user_id, query.start_date, query.end_date)
        return rows[query.offset:query.offset + query.limit]

    async def heart_rate_hours(self, day: date, timezone: str = DEFAULT_TIMEZONE):
        return await views.heart_rate_hours(self.session, self.user_id, day, timezone)

    async def samples(self, query: HealthSampleQuery):
        # Mẫu nhạy cảm (đường huyết) cần consent `sensitive` riêng của trợ lý, như context API (topic vitals).
        hidden = set() if await consent.device_access(self.session, self.user_id, "sensitive") else SENSITIVE_SAMPLES
        if query.sample_type in hidden:
            await consent.require_device_access(self.session, self.user_id, "sensitive")
        rows = await views.samples(self.session, self.user_id, query.start_date, query.end_date, query.sample_type)
        rows = [row for row in rows if row.sample_type not in hidden]
        return rows[query.offset:query.offset + query.limit]
