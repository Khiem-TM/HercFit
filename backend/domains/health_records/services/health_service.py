"""Quyền đọc dữ liệu sức khoẻ đã đồng bộ và hồ sơ sức khoẻ suy ra."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import func, select

from domains.body.models.body_metrics import BodyMetric
from domains.body.services import readings
from domains.health_records.models.device_records import DailyHealthSummary, DeviceWorkout, HealthSample, SleepSession
from domains.health_records import ports
from domains.identity import consent
from domains.health_records.schemas.health import (
    HEALTH_PROVIDER,
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


def _recent(user_id, start: date, end: date):
    return (DailyHealthSummary.user_id == user_id, DailyHealthSummary.is_active.is_(True),
            DailyHealthSummary.source == HEALTH_PROVIDER,
            DailyHealthSummary.local_date >= start, DailyHealthSummary.local_date <= end)


async def measured_resting_hr(session, user_id, today: date) -> int | None:
    """Trung vị nhịp tim nghỉ từ thiết bị trong 7 ngày gần nhất (None khi bên đọc không có quyền)."""
    if not await consent.device_access(session, user_id):
        return None
    values = sorted((await session.execute(select(DailyHealthSummary.resting_hr_bpm).where(
        *_recent(user_id, today - timedelta(days=6), today), DailyHealthSummary.resting_hr_bpm.is_not(None)))).scalars())
    return values[len(values) // 2] if values else None


async def observed_activity_level(session, user_id, today: date) -> str | None:
    """Mức vận động theo bước chân trên 28 ngày có đeo; None khi có ít hơn 7 ngày đeo."""
    if not await consent.device_access(session, user_id):
        return None
    row = (await session.execute(select(func.count(), func.avg(DailyHealthSummary.steps)).where(
        *_recent(user_id, today - timedelta(days=27), today), DailyHealthSummary.steps >= WORN_DAY_MIN_STEPS))).one()
    return activity_level_from_steps(float(row[1])) if row[0] >= MIN_WORN_DAYS_FOR_LEVEL else None


async def device_expenditure(session, user_id, today: date, days: int = 14) -> float | None:
    """Trung bình tổng năng lượng từ thiết bị trên các ngày có đeo đã trọn (trong quá khứ)."""
    if not await consent.device_access(session, user_id):
        return None
    row = (await session.execute(select(func.count(), func.avg(DailyHealthSummary.total_kcal)).where(
        *_recent(user_id, today - timedelta(days=days), today - timedelta(days=1)),
        DailyHealthSummary.total_kcal.is_not(None), DailyHealthSummary.steps >= WORN_DAY_MIN_STEPS))).one()
    return round(float(row[1])) if row[0] >= 3 else None


async def daily_expenditure(session, user_id, start: date, end: date) -> dict[date, float]:
    if not await consent.device_access(session, user_id):
        return {}
    rows = (await session.execute(select(DailyHealthSummary.local_date, DailyHealthSummary.total_kcal).where(
        *_recent(user_id, start, end), DailyHealthSummary.total_kcal.is_not(None)))).all()
    return {day: kcal for day, kcal in rows}


class HealthService(UserService):
    async def connection(self) -> ports.ProviderStatus | None:
        return await ports.provider_status(self.session, self.user_id)

    async def require_assistant_access(self, request: Request | None = None) -> None:
        """Trợ lý chỉ đọc dữ liệu thiết bị khi người dùng cho phép (identity.consent)."""
        await consent.require_device_access(self.session, self.user_id)

    async def _daily(self, start: date, end: date):
        return list((await self.session.execute(select(DailyHealthSummary).where(
            DailyHealthSummary.user_id == self.user_id, DailyHealthSummary.is_active.is_(True),
            DailyHealthSummary.local_date >= start, DailyHealthSummary.local_date <= end,
        ).order_by(DailyHealthSummary.local_date))).scalars())

    async def _by_date(self, model, start: date, end: date, limit: int = 500, offset: int = 0):
        return list((await self.session.execute(select(model).where(
            model.user_id == self.user_id, model.is_active.is_(True),
            model.local_date >= start, model.local_date <= end,
        ).order_by(model.local_date, model.id).offset(offset).limit(limit))).scalars())

    def _today(self, zone: str) -> date:
        return datetime.now(ZoneInfo(zone)).date()

    async def profile(self, timezone: str = DEFAULT_TIMEZONE, today: date | None = None) -> HealthProfileRead:
        today = today or self._today(timezone)
        connection = await self.connection()
        metrics = await BodyMetric.list_for_user(self.session, user_id=self.user_id, limit=200)
        daily = await self._daily(today - timedelta(days=27), today)
        return build_profile(today=today, zone=timezone, user=self.user, metrics=metrics, daily=daily,
                             connection=connection)

    async def overview(self, query: HealthOverviewQuery) -> HealthOverviewRead:
        from domains.analytics.services.progress_service import daily_meal_totals

        end = query.end_date or self._today(query.timezone)
        start = end - timedelta(days=query.days - 1)
        connection = await self.connection()
        daily = await self._daily(start, end)
        sleep = await self._by_date(SleepSession, start, end)
        workouts = await self._by_date(DeviceWorkout, start, end)
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
                              age=age, daily=daily, sleep=sleep, workouts=workouts, intake=intake, weights=weights)

    async def daily(self, query: DateRangeQuery):
        rows = await self._daily(query.start_date, query.end_date)
        return rows[query.offset:query.offset + query.limit]

    async def sleep(self, query: DateRangeQuery):
        return await self._by_date(SleepSession, query.start_date, query.end_date, query.limit, query.offset)

    async def workouts(self, query: DateRangeQuery):
        return await self._by_date(DeviceWorkout, query.start_date, query.end_date, query.limit, query.offset)

    async def samples(self, query: HealthSampleQuery):
        lower, upper = query.utc_bounds()
        statement = select(HealthSample).where(
            HealthSample.user_id == self.user_id, HealthSample.is_active.is_(True),
            HealthSample.measured_at >= lower, HealthSample.measured_at < upper)
        if query.sample_type:
            statement = statement.where(HealthSample.sample_type == query.sample_type)
        return list((await self.session.execute(
            statement.order_by(HealthSample.measured_at).offset(query.offset).limit(query.limit))).scalars())
