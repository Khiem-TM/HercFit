"""Một lần đọc cho trang Dashboard (trước đây khoảng 16 request song song từ trình duyệt).

Mỗi phần gọi đúng service của endpoint riêng tương ứng (/api/health/*, /api/progress, /api/meals...), nên số liệu giống
hệt; mỗi phần chạy trong SAVEPOINT riêng: phần nào lỗi trả null và tên phần nằm trong `errors`, các phần khác vẫn trả về
(trình duyệt giữ bản cũ của phần lỗi). Dữ liệu thiết bị cần consent như /api/health/*: chưa cho phép thì các phần đó là
null và nằm trong `unavailable`, không tính là lỗi.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.dependencies import UserContextDep
from core.transaction import transaction
from domains.analytics.schemas.daily_health import DailyAssessmentRead
from domains.analytics.schemas.progress import ProgressRead
from domains.analytics.services.daily_health import service as daily_health
from domains.analytics.services.progress_service import summarize_user
from domains.body.models.body_metrics import BodyMetric
from domains.body.schemas.body_metrics import BodyMetricRead
from domains.goals_plans.models.plans import TrainingPlan
from domains.goals_plans.schemas.plans import TrainingPlanRead
from domains.goals_plans.services.plan_service import PlanService
from domains.health_records.schemas.health import (
    DailyHealthRead,
    DeviceWorkoutRead,
    HealthOverviewQuery,
    HealthOverviewRead,
    HealthProfileRead,
    HealthSampleQuery,
    HealthSampleRead,
    SleepSessionRead,
)
from domains.health_records.services.health_service import HealthService
from domains.identity import consent
from domains.nutrition.models.meals import Meal
from domains.nutrition.schemas.meals import MealRead
from domains.nutrition.schemas.nutrition import NutritionTargetsRead
from domains.nutrition.services.nutrition_targets import NutritionTargetService
from domains.shared.schemas.tracking import (
    DEFAULT_TIMEZONE,
    DateRangeQuery,
    JournalQuery,
    TimeZoneName,
)
from domains.training.models.trainings import Training
from domains.training.schemas.trainings import TrainingRead
from integrations.google_health.connection import HealthConnectionService
from integrations.google_health.schemas import HealthConnectionRead

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

# Giới hạn một trang của API danh sách; bữa ăn / buổi tập đọc tiếp theo offset tới MAX_PAGES trang.
PAGE = 200
MAX_PAGES = 10
DEVICE_SECTIONS = ("profile", "overview", "daily", "sleep", "workouts", "samples", "assessment")


class DashboardRead(BaseModel):
    start_date: date
    end_date: date
    timezone: str
    connection: HealthConnectionRead | None = None
    profile: HealthProfileRead | None = None
    overview: HealthOverviewRead | None = None
    daily: list[DailyHealthRead] | None = None
    sleep: list[SleepSessionRead] | None = None
    workouts: list[DeviceWorkoutRead] | None = None
    samples: list[HealthSampleRead] | None = None
    progress: ProgressRead | None = None
    # Giữ đúng dạng của /api/v2/health/daily-assessment (bỏ trường null).
    assessment: dict[str, Any] | None = None
    targets: NutritionTargetsRead | None = None
    plan: TrainingPlanRead | None = None
    previous_plan: TrainingPlanRead | None = None
    meals: list[MealRead] | None = None
    trainings: list[TrainingRead] | None = None
    # 200 số đo mới nhất (vòng đo có thể đã cũ) gộp với mọi số đo trong khoảng ngày (mẫu thiết bị dày), không trùng.
    metrics: list[BodyMetricRead] | None = None
    errors: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


@router.get("/dashboard", response_model=DashboardRead, summary="Mọi dữ liệu trang Dashboard trong một lần đọc")
@transaction
async def get_dashboard(service: UserContextDep,
                        days: Annotated[int, Query(ge=7, le=90)] = 90,
                        timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    session, user = service.session, service.user
    end = datetime.now(ZoneInfo(timezone)).date()
    start = end - timedelta(days=days - 1)
    since = datetime.combine(start, time.min, ZoneInfo(timezone))
    # Dict (không phải DashboardRead): FastAPI kiểm tra theo response_model và đọc bản ghi ORM bằng from_attributes,
    # như các endpoint riêng.
    data: dict[str, Any] = {"start_date": start, "end_date": end, "timezone": timezone, "errors": [], "unavailable": []}

    async def section(name: str, load) -> None:
        try:
            async with session.begin_nested():
                data[name] = await load()
        except Exception:
            logger.exception("dashboard section %s failed", name)
            data["errors"].append(name)

    async def pages(model) -> list[Any]:
        rows: list[Any] = []
        for page in range(MAX_PAGES):
            query = JournalQuery(recorded_from=since, timezone=timezone, offset=page * PAGE, limit=PAGE)
            chunk = await model.list_for_user(session, user_id=user.id, query=query)
            rows.extend(chunk)
            if len(chunk) < PAGE:
                break
        return rows

    async def metrics() -> list[Any]:
        latest = await BodyMetric.list_for_user(session, user_id=user.id, limit=PAGE)
        in_range = await BodyMetric.list_for_user(session, user_id=user.id, recorded_from=since, limit=PAGE)
        merged = {row.id: row for row in [*latest, *in_range]}
        return sorted(merged.values(), key=lambda row: row.recorded_at, reverse=True)

    async def plan() -> Any:
        plans = PlanService(session, user)
        current = await plans.current(TrainingPlan)
        # Lịch đã kết thúc chỉ cần khi không có lịch đang chạy (tab Kế hoạch hiện lịch cũ).
        data["previous_plan"] = None if current is not None else await plans.previous_training_plan()
        return current

    async def assessment() -> dict[str, Any]:
        read = DailyAssessmentRead.model_validate(await daily_health.assess(session, user, day=None, zone=None))
        return read.model_dump(mode="json", exclude_none=True)

    span = {"start_date": start, "end_date": end, "timezone": timezone, "limit": PAGE}
    await section("connection", lambda: HealthConnectionService(session, user).status())
    await section("progress", lambda: summarize_user(session, user_id=user.id, options=DateRangeQuery(**span)))
    await section("targets", lambda: NutritionTargetService(session, user).targets(timezone=timezone))
    await section("plan", plan)
    await section("meals", lambda: pages(Meal))
    await section("trainings", lambda: pages(Training))
    await section("metrics", metrics)
    if not await consent.device_access(session, user.id):
        data["unavailable"].extend(DEVICE_SECTIONS)
        return data
    health = HealthService(session, user)
    await section("profile", lambda: health.profile(timezone))
    await section("overview", lambda: health.overview(HealthOverviewQuery(days=days, timezone=timezone)))
    await section("daily", lambda: health.daily(DateRangeQuery(**span)))
    await section("sleep", lambda: health.sleep(DateRangeQuery(**span)))
    await section("workouts", lambda: health.workouts(DateRangeQuery(**span)))
    await section("samples", lambda: health.samples(HealthSampleQuery(**span)))
    await section("assessment", assessment)
    return data
