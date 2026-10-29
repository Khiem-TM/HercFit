"""Athlete profile, deterministic training analytics/insights and template previews."""
from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter

from core.transaction import transaction
from models.body_metrics import BodyMetric
from routers.dependencies import UserContextDep, UserDataServiceDep, validated_query
from schemas.tracking import TimeZoneName
from schemas.training import (
    AnalyticsQuery, InsightQuery, InsightsRead, RunningSummaryRead, StrengthProgressQuery, StrengthProgressRead,
    StrengthRecordsRead, TemplateScheduleQuery, TemplateSummary, TrainingLoadRead, TrainingProfile,
    TrainingProfileRead, TrainingSummaryRead,
)
from schemas.plans import TrainingPlanCreate
from services import training_analytics as analytics
from services.training_library import RUN_WORKOUTS, build_schedule, list_templates

router = APIRouter(prefix="/training", tags=["training-analytics"])
TZ = "Asia/Ho_Chi_Minh"


def _range(start_date: date, end_date: date, timezone: str) -> AnalyticsQuery:
    return validated_query(AnalyticsQuery, start_date=start_date, end_date=end_date, timezone=timezone)


@router.get("/profile", response_model=TrainingProfileRead)
async def get_training_profile(service: UserContextDep):
    return analytics.profile_read(service.user.personal_info)


@router.put("/profile", response_model=TrainingProfileRead)
@transaction
async def put_training_profile(payload: TrainingProfile, service: UserDataServiceDep):
    user = await service.merge_personal_info({"training": payload.model_dump(mode="json")})
    return analytics.profile_read(user.personal_info)


@router.get("/summary", response_model=TrainingSummaryRead)
async def training_summary(start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    return await analytics.summary(service.session, service.user_id, _range(start_date, end_date, timezone))


@router.get("/load", response_model=TrainingLoadRead)
async def training_load(start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    return await analytics.load(service.session, service.user_id, _range(start_date, end_date, timezone))


@router.get("/strength/progress", response_model=StrengthProgressRead)
async def strength_progress(exercise_id: UUID, start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    options = validated_query(StrengthProgressQuery, exercise_id=exercise_id, start_date=start_date, end_date=end_date, timezone=timezone)
    return await analytics.strength_progress(service.session, service.user_id, options)


@router.get("/strength/records", response_model=StrengthRecordsRead)
async def strength_records(service: UserContextDep, timezone: TimeZoneName = TZ):
    return await analytics.strength_records(service.session, service.user_id, timezone=timezone)


@router.get("/running/summary", response_model=RunningSummaryRead)
async def running_summary(start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    profile = analytics.profile_read(service.user.personal_info)["profile"]
    return await analytics.running_summary(service.session, service.user_id, _range(start_date, end_date, timezone), profile)


@router.get("/insights", response_model=InsightsRead)
async def training_insights(service: UserContextDep, end_date: date | None = None, timezone: TimeZoneName = TZ):
    options = validated_query(InsightQuery, end_date=end_date, timezone=timezone)
    latest = await BodyMetric.get_latest_for_user(service.session, user_id=service.user_id)
    weight = float(latest.weight_kg) if latest is not None and latest.weight_kg is not None else None
    profile = analytics.profile_read(service.user.personal_info)["profile"]
    return await analytics.insights(service.session, service.user_id, options, profile=profile, bodyweight_kg=weight)


@router.get("/templates", response_model=list[TemplateSummary])
async def training_templates():
    return list_templates()


@router.get("/templates/workouts/{code}")
async def running_workout(code: str):
    """One running workout prescription (no exercise id; resolve run_* from the catalog)."""
    workout = RUN_WORKOUTS.get(code)
    if workout is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Workout template not found")
    exercise_code, prescription = workout["build"]()
    return {"code": code, "name_vi": workout["name_vi"], "exercise_code": exercise_code, "prescription": prescription}


@router.get("/templates/{code}/schedule", response_model=TrainingPlanCreate)
async def preview_template_schedule(code: str, service: UserContextDep, start_date: date | None = None,
                                    weeks: int | None = None, name: str | None = None):
    """Preview only: submit the returned payload to POST /plans/{plan_id}/training-plans."""
    options = validated_query(TemplateScheduleQuery, start_date=start_date or date.today() + timedelta(days=1), weeks=weeks, name=name)
    payload = await build_schedule(service.session, user_id=service.user_id, code=code, start_date=options.start_date,
                                   weeks=options.weeks, name=options.name)
    return TrainingPlanCreate.model_validate(payload)
