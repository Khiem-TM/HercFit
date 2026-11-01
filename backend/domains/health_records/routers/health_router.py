"""Synchronized health data and the derived health profile (read-only)."""
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
    SampleType,
    SleepSessionRead,
)
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, DateRangeQuery, TimeZoneName
from domains.health_records.services.health_service import HealthService

HealthServiceDep = Annotated[HealthService, service_dependency(HealthService)]


async def assistant_consent(request: Request, service: HealthServiceDep) -> None:
    await service.require_assistant_access(request)


router = APIRouter(prefix="/health", tags=["health-data"], dependencies=[Depends(assistant_consent)])


def get_overview_query(days: int = 28, timezone: TimeZoneName = DEFAULT_TIMEZONE, end_date: date | None = None):
    return validated_query(HealthOverviewQuery, days=days, timezone=timezone, end_date=end_date)


def get_range_query(pagination: PaginationDep, start_date: date, end_date: date,
                    timezone: TimeZoneName = DEFAULT_TIMEZONE):
    # Unlike the shared progress range, device series are paginated: 90 days need limit > 50.
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


@router.get("/samples", response_model=list[HealthSampleRead], summary="Chỉ số sinh tồn rời (đường huyết, nhiệt độ)")
async def list_samples(service: HealthServiceDep, query: Annotated[HealthSampleQuery, Depends(get_sample_query)]):
    return await service.samples(query)
