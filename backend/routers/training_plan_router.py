"""Dated training-plans, replaced as complete versions."""
from uuid import UUID

from fastapi import APIRouter, Response
from core.transaction import transaction
from models.plans import TrainingPlan
from schemas.plans import TrainingPlanCreate, TrainingPlanReplace, TrainingPlanRead, TrainingPlanEntryRead, PlanEnd
from routers.dependencies import PlanServiceDep, ScheduleQueryDep, ScheduleEntryQueryDep, VersionQuery
from routers.responses import created, current_or_not_found

router = APIRouter(tags=["training-plans"])


@router.post("/plans/{plan_id}/training-plans", response_model=TrainingPlanRead, status_code=201)
@transaction
async def create_training_plan(plan_id: UUID, payload: TrainingPlanCreate, service: PlanServiceDep, response: Response):
    return created(response, "training-plans", await service.create(TrainingPlan, payload, plan_id=plan_id))


@router.get("/plans/{plan_id}/training-plans", response_model=list[TrainingPlanRead])
async def list_training_plans(plan_id: UUID, options: ScheduleQueryDep, service: PlanServiceDep):
    return await service.list(TrainingPlan, options, plan_id=plan_id)


@router.get("/plans/{plan_id}/training-plans/current", response_model=TrainingPlanRead, responses={404: {"description": "No current schedule"}})
@transaction
async def current_training_plan(plan_id: UUID, service: PlanServiceDep):
    return current_or_not_found(await service.current(TrainingPlan, plan_id=plan_id), "TrainingPlan")


@router.get("/training-plans/{training_plan_id}", response_model=TrainingPlanRead)
async def get_training_plan(training_plan_id: UUID, service: PlanServiceDep, include_inactive: bool = False):
    return await service.get(TrainingPlan, training_plan_id, include_inactive=include_inactive)


@router.get("/training-plans/{training_plan_id}/entries", response_model=list[TrainingPlanEntryRead])
async def list_training_plan_entries(training_plan_id: UUID, options: ScheduleEntryQueryDep, service: PlanServiceDep):
    return await service.entries(TrainingPlan, training_plan_id, options)


@router.put("/training-plans/{training_plan_id}", response_model=TrainingPlanRead, status_code=201)
@transaction
async def replace_training_plan(training_plan_id: UUID, payload: TrainingPlanReplace, service: PlanServiceDep, response: Response):
    return created(response, "training-plans", await service.replace(TrainingPlan, training_plan_id, payload))


@router.post("/training-plans/{training_plan_id}/end", response_model=TrainingPlanRead)
@transaction
async def end_training_plan(training_plan_id: UUID, payload: PlanEnd, service: PlanServiceDep):
    return await service.end(TrainingPlan, training_plan_id, payload)


@router.delete("/training-plans/{training_plan_id}", status_code=204)
@transaction
async def delete_training_plan(training_plan_id: UUID, expected_version_id: VersionQuery, service: PlanServiceDep):
    await service.delete(TrainingPlan, training_plan_id, expected_version_id)
    return Response(status_code=204)

