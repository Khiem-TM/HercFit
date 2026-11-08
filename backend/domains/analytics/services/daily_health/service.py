"""Dựng đánh giá sức khoẻ hằng ngày lúc đọc: đọc health_points và nhật ký tập rồi gọi các hàm thuần.

Không có bảng cache: một lần đánh giá đọc 36 ngày dữ liệu theo ngày (vài chục dòng) và luôn khớp
dữ liệu, consent và phiên bản thuật toán hiện tại. Consent của bên đọc được kiểm ở router.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from domains.analytics.schemas.daily_health import DailyAssessmentRead
from domains.analytics.services.daily_health import analytics, readiness
from domains.health_records import ports, views
from domains.health_records.schemas.health import recommended_sleep_hours
from domains.training.services import training_analytics

# Nền 28 ngày trước ngày đo + 7 ngày xu hướng + 1 ngày lùi khi chỉ số hôm nay chưa có.
WINDOW_DAYS = analytics.BASELINE_DAYS + analytics.TREND_DAYS + 1


def build(*, day: date, zone: str, now: datetime, daily: list[Any], availability: dict[str, Any], status: Any,
          loads: dict, missing_rpe: int, age: int | None, sleep: list[Any] | None = None) -> DailyAssessmentRead:
    """Phần thuần của một lần đánh giá (test dùng SimpleNamespace thay cho dòng ORM).

    sleep: các phiên ngủ (SleepSessionRead) của 7 ngày thức dậy gần nhất; None khi bên gọi không đọc chúng.
    """
    by_day = {row.local_date: row for row in daily}
    readings = analytics.readings(day, by_day, availability)
    detail = None
    if sleep is not None:
        need = round(recommended_sleep_hours(age)[0] * 60)
        detail = analytics.sleep_detail(day, sleep, zone, need)
    return readiness.decide(day=day, zone=zone, readings=readings, trends=analytics.trends(day, by_day),
                            load=analytics.load_summary(day, loads, missing_rpe),
                            quality=analytics.quality(readings, status, now), age=age, sleep=detail)


async def assess(session, user, *, day: date | None = None, zone: str | None = None,
                 now: datetime | None = None) -> DailyAssessmentRead:
    zone = await ports.user_timezone(session, user.id, zone)
    now = now or datetime.now(timezone.utc)
    day = day or now.astimezone(ZoneInfo(zone)).date()
    start = day - timedelta(days=WINDOW_DAYS)
    daily = await views.daily(session, user.id, start, day, zone)
    loads, missing = await training_analytics.daily_loads(session, user.id, day - timedelta(days=35), day, zone)
    status = await ports.provider_status(session, user.id)
    age = user.age if getattr(user, "age", None) is not None else (
        (status.provider_profile or {}).get("age") if status is not None else None)
    sleep = await views.sleep(session, user.id, day - timedelta(days=analytics.TREND_DAYS - 1), day)
    return build(day=day, zone=zone, now=now, daily=daily, availability=await ports.availability(session, user.id),
                 status=status, loads=loads, missing_rpe=missing, age=age, sleep=sleep)
