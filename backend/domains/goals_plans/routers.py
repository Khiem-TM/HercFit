"""Router HTTP của miền mục tiêu và lịch tập."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from api.dependencies import (
    PaginationDep,
    PlanQueryDep,
    PlanServiceDep,
    ScheduleEntryQueryDep,
    ScheduleQueryDep,
    UserDataServiceDep,
    VersionQuery,
)
from api.responses import created, current_or_not_found
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.goals_plans.models import Plan, TrainingPlan
from domains.goals_plans.schemas import (
    EntryCompletionRead,
    GoalCreate,
    GoalRead,
    GoalUpdateRequest,
    ManualPlanReplace,
    PlanEnd,
    PlanInput,
    PlanRead,
    TrainingPlanCreate,
    TrainingPlanEntryRead,
    TrainingPlanRead,
    TrainingPlanReplace,
)

# --------------------------------------------------------------------------------------------------
# Xác nhận, xem và quản lý mục tiêu của người dùng đã xác thực.
# --------------------------------------------------------------------------------------------------

goal_router = APIRouter(route_class=IdempotentRoute, prefix="/goals", tags=["goals"])


@goal_router.post("/confirm", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
@transaction
async def confirm_goal(payload: GoalCreate, service: UserDataServiceDep):
    """Lưu mục tiêu đã chấp nhận ở trạng thái IN_PROGRESS; mục tiêu hiện tại thứ hai trả 409."""
    return await service.confirm_goal(payload)


@goal_router.get("", response_model=list[GoalRead])
async def list_goals(options: PaginationDep, service: UserDataServiceDep):
    return await service.list_goals(options)


@goal_router.get("/current", response_model=GoalRead)
async def get_current_goal(service: UserDataServiceDep):
    return await service.current_goal()


@goal_router.get("/{goal_id}", response_model=GoalRead)
async def get_goal(goal_id: UUID, service: UserDataServiceDep):
    return await service.get_goal(goal_id)


@goal_router.patch("/{goal_id}", response_model=GoalRead)
@transaction
async def update_goal(goal_id: UUID, payload: GoalUpdateRequest, service: UserDataServiceDep):
    return await service.update_goal(goal_id, payload)


@goal_router.post("/{goal_id}/complete", response_model=GoalRead)
@transaction
async def complete_goal(goal_id: UUID, service: UserDataServiceDep):
    return await service.complete_goal(goal_id)


@goal_router.post("/{goal_id}/cancel", response_model=GoalRead)
@transaction
async def cancel_goal(goal_id: UUID, service: UserDataServiceDep):
    return await service.cancel_goal(goal_id)


@goal_router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
@transaction
async def delete_goal(goal_id: UUID, service: UserDataServiceDep) -> Response:
    await service.delete_goal(goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------------------------------
# Vòng đời kế hoạch chính thủ công và thay thế có phiên bản.
# --------------------------------------------------------------------------------------------------

plan_router = APIRouter(prefix="/plans", tags=["plans"])


@plan_router.post("", response_model=PlanRead, status_code=201)
@transaction
async def create_plan(payload: PlanInput, service: PlanServiceDep, response: Response):
    return created(response, "plans", await service.create(Plan, payload))


@plan_router.get("", response_model=list[PlanRead])
async def list_plans(options: PlanQueryDep, service: PlanServiceDep):
    return await service.list(Plan, options)


@plan_router.get("/current", response_model=PlanRead, responses={404: {"description": "No current plan"}})
@transaction
async def current_plan(service: PlanServiceDep):
    return current_or_not_found(await service.current(), "Plan")


@plan_router.get("/{plan_id}", response_model=PlanRead)
async def get_plan(plan_id: UUID, service: PlanServiceDep, include_inactive: bool = False):
    return await service.get(Plan, plan_id, include_inactive=include_inactive)


@plan_router.put("/{plan_id}", response_model=PlanRead, status_code=201)
@transaction
async def replace_plan(plan_id: UUID, payload: ManualPlanReplace, service: PlanServiceDep, response: Response):
    return created(response, "plans", await service.replace(Plan, plan_id, payload))


@plan_router.post("/{plan_id}/end", response_model=PlanRead)
@transaction
async def end_plan(plan_id: UUID, payload: PlanEnd, service: PlanServiceDep):
    return await service.end(Plan, plan_id, payload)


@plan_router.delete("/{plan_id}", status_code=204)
@transaction
async def delete_plan(plan_id: UUID, expected_version_id: VersionQuery, service: PlanServiceDep):
    await service.delete(Plan, plan_id, expected_version_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------------------------------
# Kế hoạch tập theo ngày, được thay bằng phiên bản đầy đủ.
# --------------------------------------------------------------------------------------------------

training_plan_router = APIRouter(tags=["training-plans"])


@training_plan_router.post("/training-plans", response_model=TrainingPlanRead, status_code=201)
@transaction
async def create_current_training_plan(payload: TrainingPlanCreate, service: PlanServiceDep, response: Response):
    """Lịch tập của kế hoạch đang hoạt động; kế hoạch cha được tạo/nới theo mục tiêu hiện tại khi cần."""
    return created(response, "training-plans", await service.create_training_plan(payload))


@training_plan_router.get("/training-plans/current", response_model=TrainingPlanRead, responses={404: {"description": "No current schedule"}})
@transaction
async def current_schedule(service: PlanServiceDep):
    return current_or_not_found(await service.current(TrainingPlan), "TrainingPlan")


@training_plan_router.get("/training-plans/previous", response_model=TrainingPlanRead, responses={404: {"description": "No ended schedule"}})
async def previous_schedule(service: PlanServiceDep):
    """Lịch đã kết thúc gần nhất, kèm các buổi đã tick (không bao giờ bị xoá khi kết thúc sớm)."""
    return current_or_not_found(await service.previous_training_plan(), "TrainingPlan")


@training_plan_router.post("/training-plans/{training_plan_id}/entries/{entry_id}/complete", response_model=EntryCompletionRead)
@transaction
async def complete_training_plan_entry(training_plan_id: UUID, entry_id: UUID, service: PlanServiceDep):
    """Chỉ buổi của hôm nay; ghi buổi tập thật (calo, Google Health) và không hoàn tác."""
    return await service.complete_entry(training_plan_id, entry_id)


@training_plan_router.post("/plans/{plan_id}/training-plans", response_model=TrainingPlanRead, status_code=201)
@transaction
async def create_training_plan(plan_id: UUID, payload: TrainingPlanCreate, service: PlanServiceDep, response: Response):
    return created(response, "training-plans", await service.create(TrainingPlan, payload, plan_id=plan_id))


@training_plan_router.get("/plans/{plan_id}/training-plans", response_model=list[TrainingPlanRead])
async def list_training_plans(plan_id: UUID, options: ScheduleQueryDep, service: PlanServiceDep):
    return await service.list(TrainingPlan, options, plan_id=plan_id)


@training_plan_router.get("/plans/{plan_id}/training-plans/current", response_model=TrainingPlanRead, responses={404: {"description": "No current schedule"}})
@transaction
async def current_training_plan(plan_id: UUID, service: PlanServiceDep):
    return current_or_not_found(await service.current(TrainingPlan, plan_id=plan_id), "TrainingPlan")


@training_plan_router.get("/training-plans/{training_plan_id}", response_model=TrainingPlanRead)
async def get_training_plan(training_plan_id: UUID, service: PlanServiceDep, include_inactive: bool = False):
    return await service.get(TrainingPlan, training_plan_id, include_inactive=include_inactive)


@training_plan_router.get("/training-plans/{training_plan_id}/entries", response_model=list[TrainingPlanEntryRead])
async def list_training_plan_entries(training_plan_id: UUID, options: ScheduleEntryQueryDep, service: PlanServiceDep):
    return await service.entries(TrainingPlan, training_plan_id, options)


@training_plan_router.put("/training-plans/{training_plan_id}", response_model=TrainingPlanRead, status_code=201)
@transaction
async def replace_training_plan(training_plan_id: UUID, payload: TrainingPlanReplace, service: PlanServiceDep, response: Response):
    return created(response, "training-plans", await service.replace(TrainingPlan, training_plan_id, payload))


@training_plan_router.post("/training-plans/{training_plan_id}/end", response_model=TrainingPlanRead)
@transaction
async def end_training_plan(training_plan_id: UUID, payload: PlanEnd, service: PlanServiceDep):
    return await service.end(TrainingPlan, training_plan_id, payload)


@training_plan_router.delete("/training-plans/{training_plan_id}", status_code=204)
@transaction
async def delete_training_plan(training_plan_id: UUID, expected_version_id: VersionQuery, service: PlanServiceDep):
    await service.delete(TrainingPlan, training_plan_id, expected_version_id)
    return Response(status_code=204)
