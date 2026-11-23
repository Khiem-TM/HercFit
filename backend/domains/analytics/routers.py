"""Router HTTP của miền phân tích."""

import logging
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.dependencies import DateRangeQueryDep, ProgressRangeQueryDep, UserContextDep
from core.transaction import transaction
from domains.analytics import daily_health, services
from domains.analytics.schemas import (
    AssistantContextRead,
    DailyAssessmentRead,
    PlanProgressRead,
    ProgressRead,
)
from domains.analytics.services import summarize_plan, summarize_user
from domains.body.models import BodyMetric
from domains.body.schemas import BodyMetricRead
from domains.goals_plans.models import TrainingPlan
from domains.goals_plans.schemas import TrainingPlanRead
from domains.goals_plans.services import PlanService
from domains.health_records.schemas import (
    DailyHealthRead,
    DeviceWorkoutRead,
    HealthOverviewQuery,
    HealthOverviewRead,
    HealthProfileRead,
    HealthSampleQuery,
    HealthSampleRead,
    SleepSessionRead,
)
from domains.health_records.services import HealthService
from domains.identity import consent
from domains.nutrition.models import Meal
from domains.nutrition.schemas import MealRead, NutritionTargetsRead
from domains.nutrition.services import NutritionTargetService
from domains.shared.schemas import DEFAULT_TIMEZONE, DateRangeQuery, JournalQuery, TimeZoneName
from domains.training.models import Training
from domains.training.schemas import TrainingRead
from integrations.google_health.connection import HealthConnectionService
from integrations.google_health.schemas import HealthConnectionRead

# --------------------------------------------------------------------------------------------------
# Ngữ cảnh chỉ đọc cho trợ lý HercFit (mỗi lượt hội thoại một lượt gọi).
# --------------------------------------------------------------------------------------------------

assistant_router = APIRouter(prefix="/assistant", tags=["assistant"])


@assistant_router.get("/context", response_model=AssistantContextRead)
async def get_assistant_context(service: UserContextDep, timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    # Ai đọc (người dùng hay trợ lý) lấy từ principal đã xác thực, không phải header.
    return await services.build_assistant_context(service.session, service.user, timezone=timezone)


# --------------------------------------------------------------------------------------------------
# /api/v2/assistant/context: ngữ cảnh có nguồn, có ngân sách cho trợ lý (và cho chính người dùng xem).
# --------------------------------------------------------------------------------------------------

context_router = APIRouter(prefix="/assistant", tags=["assistant"])
Topic = Literal["overview", "activity", "sleep", "recovery", "body", "nutrition", "vitals"]
Period = Literal["7d", "28d", "90d"]


class ContextRead(BaseModel):
    topic: str
    period: str
    items: list[dict]
    withheld: list[str]
    consent_version: int
    truncated: int
    tokens: int
    budget: int


class ContextQueryRead(BaseModel):
    sections: list[ContextRead]
    tokens: int
    budget: int


@context_router.get("/context", response_model=ContextRead, summary="Ngữ cảnh sức khoẻ có nguồn gốc cho trợ lý",
            description="Mỗi mục có giá trị, đơn vị, nguồn, thời điểm đo, độ mới, độ phủ dữ liệu và phương pháp. "
                        "Dữ liệu thiết bị cần đồng ý của người dùng; dữ liệu nhạy cảm cần đồng ý riêng.")
async def get_context(service: UserContextDep, topic: Topic = "overview", period: Period = "28d",
                      budget: Annotated[int, Query(ge=200, le=services.BASE_BUDGET * 2)] = services.BASE_BUDGET,
                      timezone: TimeZoneName | None = None):
    context = await services.get_context(service.session, service.user, topic=topic, period=period, budget=budget,
                                    zone=timezone)
    await service.session.commit()
    return context


@context_router.get("/context:query", response_model=ContextQueryRead, summary="Truy vấn ngữ cảnh sâu theo chủ đề",
            description="Chỉ đọc (GET): nhiều chủ đề trong một ngân sách token, mặc định 4.000.")
async def query_context(service: UserContextDep, topics: Annotated[list[Topic], Query(min_length=1, max_length=8)],
                        period: Period = "28d",
                        budget: Annotated[int, Query(ge=200, le=8000)] = services.DEEP_BUDGET,
                        timezone: TimeZoneName | None = None):
    sections, used = [], 0
    for topic in dict.fromkeys(topics):
        remaining = budget - used
        if remaining < 100:
            break
        section = await services.get_context(service.session, service.user, topic=topic, period=period,
                                        budget=remaining, zone=timezone)
        sections.append(section)
        used += section["tokens"]
    await service.session.commit()
    return ContextQueryRead(sections=sections, tokens=used, budget=budget)


# --------------------------------------------------------------------------------------------------
# Một lần đọc cho trang Dashboard (trước đây khoảng 16 request song song từ trình duyệt).
#
# Mỗi phần gọi đúng service của endpoint riêng tương ứng (/api/health/*, /api/progress, /api/meals...), nên số liệu giống
# hệt; mỗi phần chạy trong SAVEPOINT riêng: phần nào lỗi trả null và tên phần nằm trong `errors`, các phần khác vẫn trả về
# (trình duyệt giữ bản cũ của phần lỗi). Dữ liệu thiết bị cần consent như /api/health/*: chưa cho phép thì các phần đó là
# null và nằm trong `unavailable`, không tính là lỗi.
# --------------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)
dashboard_router = APIRouter(tags=["dashboard"])

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


@dashboard_router.get("/dashboard", response_model=DashboardRead, summary="Mọi dữ liệu trang Dashboard trong một lần đọc")
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


# --------------------------------------------------------------------------------------------------
# Tổng thực tế theo ngày và so sánh với chỉ tiêu tường minh của kế hoạch.
# --------------------------------------------------------------------------------------------------

progress_router = APIRouter(tags=["progress"])


@progress_router.get("/progress", response_model=ProgressRead)
async def get_progress(options: DateRangeQueryDep, service: UserContextDep):
    return await summarize_user(service.session, user_id=service.user_id, options=options)


@progress_router.get("/plans/{plan_id}/progress", response_model=PlanProgressRead)
async def get_plan_progress(plan_id: UUID, options: ProgressRangeQueryDep, service: UserContextDep):
    return await summarize_plan(service.session, user_id=service.user_id, plan_id=plan_id, **options.model_dump())
