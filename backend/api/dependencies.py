"""Phụ thuộc service đã xác thực và query đã kiểm tra, dùng chung."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Query
from pydantic import AwareDatetime, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from domains.body.schemas.body_metrics import BodyMetricQuery
from domains.catalog.schemas.exercises import ExerciseKind, ExerciseQuery
from domains.catalog.schemas.foods import FoodQuery
from domains.catalog.services.catalog_service import CatalogService
from domains.goals_plans.schemas.plans import PlanQuery, PlanStatus
from domains.goals_plans.services.plan_service import PlanService
from domains.identity.models.user import User
from domains.identity.services.user_data_service import UserDataService, request_validation_error
from domains.shared.schemas.common import Pagination
from domains.shared.schemas.enums import FoodItemType, FoodSourceType
from domains.shared.schemas.tracking import (
    DateRangeQuery,
    JournalQuery,
    ProgressRangeQuery,
    ScheduleEntryQuery,
    TimeZoneName,
)
from domains.shared.services.common import UserService
from domains.shared.services.journal_service import JournalService

SessionDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
VersionQuery = Annotated[int, Query(ge=1)]


def service_dependency(service_type):
    def provide(session: SessionDep, user: CurrentUserDep):
        return service_type(session, user)
    return Depends(provide)


CatalogServiceDep = Annotated[CatalogService, service_dependency(CatalogService)]
JournalServiceDep = Annotated[JournalService, service_dependency(JournalService)]
PlanServiceDep = Annotated[PlanService, service_dependency(PlanService)]
UserContextDep = Annotated[UserService, service_dependency(UserService)]


def validated_query(schema, **values):
    try:
        return schema(**values)
    except ValidationError as exc:
        raise request_validation_error(exc, "query") from exc


def get_user_data_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> UserDataService:
    return UserDataService(session, user)


UserDataServiceDep = Annotated[UserDataService, Depends(get_user_data_service)]


def get_pagination(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include_inactive: bool = False,
) -> Pagination:
    return Pagination(offset=offset, limit=limit, include_inactive=include_inactive)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]


def get_metric_query(
    pagination: PaginationDep,
    recorded_from: Annotated[AwareDatetime | None, Query()] = None,
    recorded_to: Annotated[AwareDatetime | None, Query()] = None,
) -> BodyMetricQuery:
    try:
        return BodyMetricQuery(
            **pagination.model_dump(), recorded_from=recorded_from, recorded_to=recorded_to,
        )
    except ValidationError as exc:
        raise request_validation_error(exc, "query") from exc


BodyMetricQueryDep = Annotated[BodyMetricQuery, Depends(get_metric_query)]


def get_food_query(pagination: PaginationDep, search: str | None = None,
                   source_type: FoodSourceType | None = None, item_type: FoodItemType | None = None,
                   sort: Literal["relevance", "protein_density"] = "relevance",
                   names: Annotated[list[str] | None, Query()] = None):
    return validated_query(FoodQuery, **pagination.model_dump(), search=search, source_type=source_type,
                           item_type=item_type, sort=sort, names=names)


def get_exercise_query(pagination: PaginationDep, search: str | None = None,
                       source_type: FoodSourceType | None = None, kind: ExerciseKind | None = None):
    return validated_query(ExerciseQuery, **pagination.model_dump(), search=search, source_type=source_type, kind=kind)


def get_plan_query(pagination: PaginationDep, status: PlanStatus | None = None, goal_id: UUID | None = None):
    return validated_query(PlanQuery, **pagination.model_dump(), status=status, goal_id=goal_id)


def get_schedule_query(pagination: PaginationDep, status: PlanStatus | None = None):
    return validated_query(PlanQuery, **pagination.model_dump(), status=status)


def get_entry_query(pagination: PaginationDep, on_date: date | None = None,
                    start_date: date | None = None, end_date: date | None = None):
    return validated_query(ScheduleEntryQuery, **pagination.model_dump(), on_date=on_date,
                           start_date=start_date, end_date=end_date)


def get_journal_query(pagination: PaginationDep, on_date: date | None = None,
                      timezone: TimeZoneName = "Asia/Ho_Chi_Minh",
                      recorded_from: AwareDatetime | None = None, recorded_to: AwareDatetime | None = None):
    return validated_query(JournalQuery, **pagination.model_dump(), on_date=on_date, timezone=timezone,
                           recorded_from=recorded_from, recorded_to=recorded_to)


def get_date_range(start_date: date, end_date: date, timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    return validated_query(DateRangeQuery, start_date=start_date, end_date=end_date, timezone=timezone)


def get_progress_range(start_date: date | None = None, end_date: date | None = None):
    return validated_query(ProgressRangeQuery, start_date=start_date, end_date=end_date)


FoodQueryDep = Annotated[FoodQuery, Depends(get_food_query)]
ExerciseQueryDep = Annotated[ExerciseQuery, Depends(get_exercise_query)]
PlanQueryDep = Annotated[PlanQuery, Depends(get_plan_query)]
ScheduleQueryDep = Annotated[PlanQuery, Depends(get_schedule_query)]
ScheduleEntryQueryDep = Annotated[ScheduleEntryQuery, Depends(get_entry_query)]
JournalQueryDep = Annotated[JournalQuery, Depends(get_journal_query)]
DateRangeQueryDep = Annotated[DateRangeQuery, Depends(get_date_range)]
ProgressRangeQueryDep = Annotated[ProgressRangeQuery, Depends(get_progress_range)]
