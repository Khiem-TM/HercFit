"""Dated meal-plans, replaced as complete versions."""
from uuid import UUID

from fastapi import APIRouter, Response
from core.transaction import transaction
from models.plans import MealPlan
from schemas.plans import MealPlanCreate, MealPlanReplace, MealPlanRead, MealPlanEntryRead, PlanEnd
from routers.dependencies import PlanServiceDep, ScheduleQueryDep, ScheduleEntryQueryDep, VersionQuery
from routers.responses import created, current_or_not_found

router = APIRouter(tags=["meal-plans"])


@router.post("/plans/{plan_id}/meal-plans", response_model=MealPlanRead, status_code=201)
@transaction
async def create_meal_plan(plan_id: UUID, payload: MealPlanCreate, service: PlanServiceDep, response: Response):
    return created(response, "meal-plans", await service.create(MealPlan, payload, plan_id=plan_id))


@router.get("/plans/{plan_id}/meal-plans", response_model=list[MealPlanRead])
async def list_meal_plans(plan_id: UUID, options: ScheduleQueryDep, service: PlanServiceDep):
    return await service.list(MealPlan, options, plan_id=plan_id)


@router.get("/plans/{plan_id}/meal-plans/current", response_model=MealPlanRead, responses={404: {"description": "No current schedule"}})
@transaction
async def current_meal_plan(plan_id: UUID, service: PlanServiceDep):
    return current_or_not_found(await service.current(MealPlan, plan_id=plan_id), "MealPlan")


@router.get("/meal-plans/{meal_plan_id}", response_model=MealPlanRead)
async def get_meal_plan(meal_plan_id: UUID, service: PlanServiceDep, include_inactive: bool = False):
    return await service.get(MealPlan, meal_plan_id, include_inactive=include_inactive)


@router.get("/meal-plans/{meal_plan_id}/entries", response_model=list[MealPlanEntryRead])
async def list_meal_plan_entries(meal_plan_id: UUID, options: ScheduleEntryQueryDep, service: PlanServiceDep):
    return await service.entries(MealPlan, meal_plan_id, options)


@router.put("/meal-plans/{meal_plan_id}", response_model=MealPlanRead, status_code=201)
@transaction
async def replace_meal_plan(meal_plan_id: UUID, payload: MealPlanReplace, service: PlanServiceDep, response: Response):
    return created(response, "meal-plans", await service.replace(MealPlan, meal_plan_id, payload))


@router.post("/meal-plans/{meal_plan_id}/end", response_model=MealPlanRead)
@transaction
async def end_meal_plan(meal_plan_id: UUID, payload: PlanEnd, service: PlanServiceDep):
    return await service.end(MealPlan, meal_plan_id, payload)


@router.delete("/meal-plans/{meal_plan_id}", status_code=204)
@transaction
async def delete_meal_plan(meal_plan_id: UUID, expected_version_id: VersionQuery, service: PlanServiceDep):
    await service.delete(MealPlan, meal_plan_id, expected_version_id)
    return Response(status_code=204)

