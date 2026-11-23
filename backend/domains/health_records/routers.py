"""Router HTTP của miền dữ liệu sức khoẻ."""

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.dependencies import PaginationDep, UserContextDep, service_dependency, validated_query
from domains.analytics import daily_health
from domains.analytics.schemas import DailyAssessmentRead
from domains.health_records import ports, views
from domains.health_records.schemas import (
    DailyHealthRead,
    DeviceWorkoutRead,
    HealthOverviewQuery,
    HealthOverviewRead,
    HealthProfileRead,
    HealthSampleQuery,
    HealthSampleRead,
    HeartRateHourRead,
    SampleType,
    SleepSessionRead,
)
from domains.health_records.services import HealthService
from domains.identity import consent
from domains.shared.schemas import DEFAULT_TIMEZONE, DateRangeQuery, TimeZoneName

# --------------------------------------------------------------------------------------------------
# Dữ liệu sức khoẻ đã đồng bộ và hồ sơ sức khoẻ suy ra (chỉ đọc).
# --------------------------------------------------------------------------------------------------

HealthServiceDep = Annotated[HealthService, service_dependency(HealthService)]


async def assistant_consent(request: Request, service: HealthServiceDep) -> None:
    await service.require_assistant_access(request)


health_router = APIRouter(prefix="/health", tags=["health-data"], dependencies=[Depends(assistant_consent)])


def get_overview_query(days: int = 28, timezone: TimeZoneName = DEFAULT_TIMEZONE, end_date: date | None = None):
    return validated_query(HealthOverviewQuery, days=days, timezone=timezone, end_date=end_date)


def get_range_query(pagination: PaginationDep, start_date: date, end_date: date,
                    timezone: TimeZoneName = DEFAULT_TIMEZONE):
    # Khác với khoảng tiến độ dùng chung, chuỗi thiết bị được phân trang: 90 ngày cần limit > 50.
    return validated_query(DateRangeQuery, **pagination.model_dump(), start_date=start_date, end_date=end_date,
                           timezone=timezone)


RangeQueryDep = Annotated[DateRangeQuery, Depends(get_range_query)]


def get_sample_query(pagination: PaginationDep, start_date: date, end_date: date,
                     timezone: TimeZoneName = DEFAULT_TIMEZONE, sample_type: SampleType | None = None):
    return validated_query(HealthSampleQuery, **pagination.model_dump(), start_date=start_date, end_date=end_date,
                           timezone=timezone, sample_type=sample_type)


@health_router.get("/profile", response_model=HealthProfileRead, summary="Hồ sơ sức khoẻ hợp nhất",
            description="Giá trị hiệu lực kèm nguồn (khai báo, thiết bị đo, nhà cung cấp, suy luận), "
                        "các trường còn thiếu và xung đột giữa khai báo với số đo.")
async def get_profile(service: HealthServiceDep, timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    return await service.profile(timezone)


@health_router.get("/overview", response_model=HealthOverviewRead, summary="Phân tích vận động, giấc ngủ, phục hồi, năng lượng")
async def get_overview(service: HealthServiceDep, query: Annotated[HealthOverviewQuery, Depends(get_overview_query)]):
    return await service.overview(query)


@health_router.get("/daily", response_model=list[DailyHealthRead], summary="Tổng hợp theo ngày từ thiết bị")
async def list_daily(service: HealthServiceDep, query: RangeQueryDep):
    return await service.daily(query)


@health_router.get("/sleep", response_model=list[SleepSessionRead], summary="Các phiên ngủ")
async def list_sleep(service: HealthServiceDep, query: RangeQueryDep):
    return await service.sleep(query)


@health_router.get("/workouts", response_model=list[DeviceWorkoutRead], summary="Buổi vận động ghi bởi thiết bị")
async def list_workouts(service: HealthServiceDep, query: RangeQueryDep):
    return await service.workouts(query)


@health_router.get("/heart-rate/hourly", response_model=list[HeartRateHourRead], summary="Nhịp tim theo giờ của một ngày",
            description="TB/thấp nhất/cao nhất mỗi giờ có dữ liệu (rollUp của Google Health); giờ không có mẫu bị bỏ.")
async def heart_rate_hourly(service: HealthServiceDep, day: Annotated[date, Query(alias="date")],
                            timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    return await service.heart_rate_hours(day, timezone)


@health_router.get("/samples", response_model=list[HealthSampleRead], summary="Chỉ số sinh tồn rời (đường huyết, nhiệt độ)")
async def list_samples(service: HealthServiceDep, query: Annotated[HealthSampleQuery, Depends(get_sample_query)]):
    return await service.samples(query)


# --------------------------------------------------------------------------------------------------
# /api/v2/health: phiên ngủ / buổi tập kèm chi tiết và insight (nền 28 ngày, độ phủ dữ liệu).
#
# Phân trang bằng cursor; trợ lý cần consent thiết bị (identity.consent). Lệnh ghi xuyên qua lên
# Google (buổi thể thao, cân nặng, nước...) nằm ở /api/v2/health/records (integrations/google_health).
# --------------------------------------------------------------------------------------------------

health_v2_router = APIRouter(prefix="/health", tags=["health-data"])


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None


def _cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        moment, item = value.split("|", 1)
        return datetime.fromisoformat(moment), UUID(item)
    except ValueError:
        raise HTTPException(422, "Invalid cursor") from None


@health_v2_router.get("/sessions", response_model=Page, summary="Phiên ngủ / buổi tập trên Google Health kèm chi tiết")
async def sessions(service: UserContextDep, kind: Literal["sleep", "workout"], start_date: date, end_date: date,
                   cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    await consent.require_device_access(service.session, service.user_id)
    rows, field = ((await views.sleep_rows(service.session, service.user_id, start_date, end_date), "start_at")
                   if kind == "sleep" else
                   (await views.workout_rows(service.session, service.user_id, start_date, end_date), "started_at"))
    rows.sort(key=lambda row: (row[field], str(row["id"])), reverse=True)
    after = _cursor(cursor)
    if after:
        rows = [row for row in rows if (row[field], str(row["id"])) < (after[0], str(after[1]))]
    page = rows[:limit]
    return Page(items=page, next_cursor=f"{page[-1][field].isoformat()}|{page[-1]['id']}" if len(rows) > limit else None)


@health_v2_router.get("/insights", summary="Phân tích có phương pháp: nền 28 ngày và độ phủ dữ liệu")
async def insights(service: UserContextDep, days: Annotated[int, Query(ge=7, le=90)] = 28,
                   end_date: date | None = None, timezone: TimeZoneName | None = None):
    await consent.require_device_access(service.session, service.user_id)
    zone = await ports.user_timezone(service.session, service.user_id, timezone)
    today = datetime.now(ZoneInfo(zone)).date()
    end = end_date or today
    start = end - timedelta(days=days - 1)
    report = await daily_health.coverage(service.session, service.user_id, start, end)
    baselines = await daily_health.baselines_for(service.session, service.user_id, end, days, today=today)
    return {
        "start_date": start, "end_date": end, "timezone": zone,
        "baselines": [{"metric": b.metric, "label": daily_health.BASELINE_METRICS[b.metric], "value": b.value,
                       "spread": b.spread, "mad": b.mad, "n": b.n, "window_days": b.window_days, "as_of": b.as_of,
                       "method": "median of complete days before as_of", "algorithm_version": b.algorithm_version}
                      for b in baselines.values()],
        "coverage": {column: {key: value for key, value in entry.items() if key != "by_day"}
                     for column, entry in report.items()},
    }


@health_v2_router.get("/daily-assessment", response_model=DailyAssessmentRead, response_model_exclude_none=True,
            summary="Đánh giá sức khoẻ hằng ngày: chỉ số so với nền cá nhân, xu hướng và độ sẵn sàng tập luyện",
            description="Tất định, tính lúc đọc (domains/analytics/daily_health.py). Mỗi lý do mang giá trị, "
                        "đường nền và đơn vị; thiếu dữ liệu được nêu rõ. Heuristic gợi ý cường độ tập, không phải "
                        "chẩn đoán. Trợ lý cần consent thiết bị.")
async def daily_assessment(service: UserContextDep, day: Annotated[date | None, Query(alias="date")] = None,
                           timezone: TimeZoneName | None = None):
    await consent.require_device_access(service.session, service.user_id)
    return await daily_health.assess(service.session, service.user, day=day, zone=timezone)
