"""Bữa ăn thực tế: ảnh chụp bất biến đầy đủ."""
from uuid import UUID

from fastapi import APIRouter, Response

from api.dependencies import JournalQueryDep, JournalServiceDep, VersionQuery
from api.responses import created
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.nutrition.models.meals import Meal
from domains.nutrition.schemas.meals import MealCreate, MealRead, MealReplace

router = APIRouter(route_class=IdempotentRoute, prefix="/meals", tags=["meals"])


@router.post("", response_model=MealRead, status_code=201)
@transaction
async def create_meal(payload: MealCreate, service: JournalServiceDep, response: Response):
    return created(response, "meals", await service.create(Meal, payload))


@router.get("", response_model=list[MealRead])
async def list_meals(options: JournalQueryDep, service: JournalServiceDep):
    return await service.list(Meal, options)


@router.get("/{meal_id}", response_model=MealRead)
async def get_meal(meal_id: UUID, service: JournalServiceDep, include_inactive: bool = False):
    return await service.get(Meal, meal_id, include_inactive=include_inactive)


@router.put("/{meal_id}", response_model=MealRead, status_code=201)
@transaction
async def replace_meal(meal_id: UUID, payload: MealReplace, service: JournalServiceDep, response: Response):
    return created(response, "meals", await service.replace(Meal, meal_id, payload))


@router.delete("/{meal_id}", status_code=204)
@transaction
async def delete_meal(meal_id: UUID, expected_version_id: VersionQuery, service: JournalServiceDep):
    await service.delete(Meal, meal_id, expected_version_id)
    return Response(status_code=204)

