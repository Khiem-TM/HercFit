"""Dữ liệu sức khoẻ đã đồng bộ và hồ sơ sức khoẻ suy ra (chỉ đọc)."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from api.dependencies import PaginationDep, service_dependency, validated_query
from domains.health_records.schemas.health import (
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
from domains.health_records.services.health_service import HealthService
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, DateRangeQuery, TimeZoneName

HealthServiceDep = Annotated[HealthService, service_dependency(HealthService)]


async def assistant_consent(request: Request, service: HealthServiceDep) -> None:
    await service.require_assistant_access(request)


router = APIRouter(prefix="/health", tags=["health-data"], dependencies=[Depends(assistant_consent)])


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


@router.get("/profile", response_model=HealthProfileRead, summary="Hồ sơ sức khoẻ hợp nhất",
            description="Giá trị hiệu lực kèm nguồn (khai báo, thiết bị đo, nhà cung cấp, suy luận), "
                        "các trường còn thiếu và xung đột giữa khai báo với số đo.")
async def get_profile(service: HealthServiceDep, timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    return await service.profile(timezone)


@router.get("/overview", response_model=HealthOverviewRead, summary="Phân tích vận động, giấc ngủ, phục hồi, năng lượng")
async def get_overview(service: HealthServiceDep, query: Annotated[HealthOverviewQuery, Depends(get_overview_query)]):
    return await service.overview(query)


@router.get("/daily", response_model=list[DailyHealthRead], summary="Tổng hợp theo ngày từ thiết bị")
async def list_daily(service: HealthServiceDep, query: RangeQueryDep):
    return await service.daily(query)


@router.get("/sleep", response_model=list[SleepSessionRead], summary="Các phiên ngủ")
async def list_sleep(service: HealthServiceDep, query: RangeQueryDep):
    return await service.sleep(query)


@router.get("/workouts", response_model=list[DeviceWorkoutRead], summary="Buổi vận động ghi bởi thiết bị")
async def list_workouts(service: HealthServiceDep, query: RangeQueryDep):
    return await service.workouts(query)


@router.get("/heart-rate/hourly", response_model=list[HeartRateHourRead], summary="Nhịp tim theo giờ của một ngày",
            description="TB/thấp nhất/cao nhất mỗi giờ có dữ liệu (rollUp của Google Health); giờ không có mẫu bị bỏ.")
async def heart_rate_hourly(service: HealthServiceDep, day: Annotated[date, Query(alias="date")],
                            timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    return await service.heart_rate_hours(day, timezone)


@router.get("/samples", response_model=list[HealthSampleRead], summary="Chỉ số sinh tồn rời (đường huyết, nhiệt độ)")
async def list_samples(service: HealthServiceDep, query: Annotated[HealthSampleQuery, Depends(get_sample_query)]):
    return await service.samples(query)
