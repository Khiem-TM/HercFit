"""Manual master plan lifecycle and versioned replacement."""
from uuid import UUID

from fastapi import APIRouter, Response
from core.transaction import transaction
from models.plans import Plan
from schemas.plans import PlanInput, ManualPlanReplace, PlanRead, PlanEnd
from routers.dependencies import PlanServiceDep, PlanQueryDep, VersionQuery
from routers.responses import created, current_or_not_found

router = APIRouter(prefix="/plans", tags=["plans"])


@router.post("", response_model=PlanRead, status_code=201)
@transaction
async def create_plan(payload: PlanInput, service: PlanServiceDep, response: Response):
    return created(response, "plans", await service.create(Plan, payload))


@router.get("", response_model=list[PlanRead])
async def list_plans(options: PlanQueryDep, service: PlanServiceDep):
    return await service.list(Plan, options)


@router.get("/current", response_model=PlanRead, responses={404: {"description": "No current plan"}})
@transaction
async def current_plan(service: PlanServiceDep):
    return current_or_not_found(await service.current(), "Plan")


@router.get("/{plan_id}", response_model=PlanRead)
async def get_plan(plan_id: UUID, service: PlanServiceDep, include_inactive: bool = False):
    return await service.get(Plan, plan_id, include_inactive=include_inactive)


@router.put("/{plan_id}", response_model=PlanRead, status_code=201)
@transaction
async def replace_plan(plan_id: UUID, payload: ManualPlanReplace, service: PlanServiceDep, response: Response):
    return created(response, "plans", await service.replace(Plan, plan_id, payload))


@router.post("/{plan_id}/end", response_model=PlanRead)
@transaction
async def end_plan(plan_id: UUID, payload: PlanEnd, service: PlanServiceDep):
    return await service.end(Plan, plan_id, payload)


@router.delete("/{plan_id}", status_code=204)
@transaction
async def delete_plan(plan_id: UUID, expected_version_id: VersionQuery, service: PlanServiceDep):
    await service.delete(Plan, plan_id, expected_version_id)
    return Response(status_code=204)
