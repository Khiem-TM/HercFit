"""Router HTTP của miền tập luyện."""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Response

from api.dependencies import (
    JournalQueryDep,
    JournalServiceDep,
    UserContextDep,
    UserDataServiceDep,
    VersionQuery,
    validated_query,
)
from api.responses import created
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.body.models import BodyMetric
from domains.catalog.services import RUN_WORKOUTS, build_schedule, list_templates
from domains.goals_plans.schemas import TrainingPlanCreate
from domains.health_records.services import measured_resting_hr
from domains.shared.schemas import TimeZoneName
from domains.training import services as analytics
from domains.training.models import Training
from domains.training.schemas import (
    AnalyticsQuery,
    InsightQuery,
    InsightsRead,
    RunningSummaryRead,
    StrengthProgressQuery,
    StrengthProgressRead,
    StrengthRecordsRead,
    TemplateScheduleQuery,
    TemplateSummary,
    TrainingCreate,
    TrainingLoadRead,
    TrainingProfile,
    TrainingProfileRead,
    TrainingRead,
    TrainingReplace,
    TrainingSummaryRead,
)

# --------------------------------------------------------------------------------------------------
# Hồ sơ vận động viên, phân tích/insight tập luyện tất định và xem trước giáo án mẫu.
# --------------------------------------------------------------------------------------------------

training_analytics_router = APIRouter(prefix="/training", tags=["training-analytics"])
TZ = "Asia/Ho_Chi_Minh"


def _range(start_date: date, end_date: date, timezone: str) -> AnalyticsQuery:
    return validated_query(AnalyticsQuery, start_date=start_date, end_date=end_date, timezone=timezone)


@training_analytics_router.get("/profile", response_model=TrainingProfileRead)
async def get_training_profile(service: UserContextDep):
    measured = await measured_resting_hr(service.session, service.user_id, analytics.today_in(TZ))
    return analytics.profile_read(service.user.personal_info, measured)


@training_analytics_router.put("/profile", response_model=TrainingProfileRead)
@transaction
async def put_training_profile(payload: TrainingProfile, service: UserDataServiceDep):
    user = await service.merge_personal_info({"training": payload.model_dump(mode="json")})
    measured = await measured_resting_hr(service.session, service.user_id, analytics.today_in(TZ))
    return analytics.profile_read(user.personal_info, measured)


@training_analytics_router.get("/summary", response_model=TrainingSummaryRead)
async def training_summary(start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    return await analytics.summary(service.session, service.user_id, _range(start_date, end_date, timezone))


@training_analytics_router.get("/load", response_model=TrainingLoadRead)
async def training_load(start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    return await analytics.load(service.session, service.user_id, _range(start_date, end_date, timezone))


@training_analytics_router.get("/strength/progress", response_model=StrengthProgressRead)
async def strength_progress(exercise_id: UUID, start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    options = validated_query(StrengthProgressQuery, exercise_id=exercise_id, start_date=start_date, end_date=end_date, timezone=timezone)
    return await analytics.strength_progress(service.session, service.user_id, options)


@training_analytics_router.get("/strength/records", response_model=StrengthRecordsRead)
async def strength_records(service: UserContextDep, timezone: TimeZoneName = TZ):
    return await analytics.strength_records(service.session, service.user_id, timezone=timezone)


@training_analytics_router.get("/running/summary", response_model=RunningSummaryRead)
async def running_summary(start_date: date, end_date: date, service: UserContextDep, timezone: TimeZoneName = TZ):
    profile = analytics.profile_read(service.user.personal_info)["profile"]
    return await analytics.running_summary(service.session, service.user_id, _range(start_date, end_date, timezone), profile)


@training_analytics_router.get("/insights", response_model=InsightsRead)
async def training_insights(service: UserContextDep, end_date: date | None = None, timezone: TimeZoneName = TZ):
    options = validated_query(InsightQuery, end_date=end_date, timezone=timezone)
    latest = await BodyMetric.get_latest_for_user(service.session, user_id=service.user_id)
    weight = float(latest.weight_kg) if latest is not None and latest.weight_kg is not None else None
    profile = analytics.profile_read(service.user.personal_info)["profile"]
    return await analytics.insights(service.session, service.user_id, options, profile=profile, bodyweight_kg=weight)


@training_analytics_router.get("/templates", response_model=list[TemplateSummary])
async def training_templates():
    return list_templates()


@training_analytics_router.get("/templates/workouts/{code}")
async def running_workout(code: str):
    """Một chỉ định bài chạy (không có exercise id; tra run_* trong catalog)."""
    workout = RUN_WORKOUTS.get(code)
    if workout is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Workout template not found")
    exercise_code, prescription = workout["build"]()
    return {"code": code, "name_vi": workout["name_vi"], "exercise_code": exercise_code, "prescription": prescription}


@training_analytics_router.get("/templates/{code}/schedule", response_model=TrainingPlanCreate)
async def preview_template_schedule(code: str, service: UserContextDep, start_date: date | None = None,
                                    weeks: int | None = None, name: str | None = None):
    """Chỉ xem trước: gửi payload trả về tới POST /training-plans (create_training_plans)."""
    options = validated_query(TemplateScheduleQuery, start_date=start_date or date.today() + timedelta(days=1), weeks=weeks, name=name)
    payload = await build_schedule(service.session, user_id=service.user_id, code=code, start_date=options.start_date,
                                   weeks=options.weeks, name=options.name)
    return TrainingPlanCreate.model_validate(payload)


# --------------------------------------------------------------------------------------------------
# Buổi tập thực tế: ảnh chụp bất biến đầy đủ.
# --------------------------------------------------------------------------------------------------

training_router = APIRouter(route_class=IdempotentRoute, prefix="/trainings", tags=["trainings"])


@training_router.post("", response_model=TrainingRead, status_code=201)
@transaction
async def create_training(payload: TrainingCreate, service: JournalServiceDep, response: Response):
    return created(response, "trainings", await service.create(Training, payload))


@training_router.get("", response_model=list[TrainingRead])
async def list_trainings(options: JournalQueryDep, service: JournalServiceDep):
    return await service.list(Training, options)


@training_router.get("/{training_id}", response_model=TrainingRead)
async def get_training(training_id: UUID, service: JournalServiceDep, include_inactive: bool = False):
    return await service.get(Training, training_id, include_inactive=include_inactive)


@training_router.put("/{training_id}", response_model=TrainingRead, status_code=201)
@transaction
async def replace_training(training_id: UUID, payload: TrainingReplace, service: JournalServiceDep, response: Response):
    return created(response, "trainings", await service.replace(Training, training_id, payload))


@training_router.delete("/{training_id}", status_code=204)
@transaction
async def delete_training(training_id: UUID, expected_version_id: VersionQuery, service: JournalServiceDep):
    await service.delete(Training, training_id, expected_version_id)
    return Response(status_code=204)
