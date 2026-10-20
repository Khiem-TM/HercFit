"""Personal foods catalog endpoints."""
from uuid import UUID

from fastapi import APIRouter, Response
from core.transaction import transaction
from models.foods import FoodItem
from schemas.foods import FoodCreate, FoodRead, FoodUpdateRequest
from schemas.tracking import VersionedRequest
from routers.dependencies import CatalogServiceDep, FoodQueryDep, VersionQuery
from routers.responses import created

router = APIRouter(prefix="/foods", tags=["foods"])


@router.post("", response_model=FoodRead, status_code=201)
@transaction
async def create_food(payload: FoodCreate, service: CatalogServiceDep, response: Response):
    return created(response, "foods", await service.create(FoodItem, payload))


@router.get("", response_model=list[FoodRead])
async def list_foods(options: FoodQueryDep, service: CatalogServiceDep):
    return await service.list(FoodItem, options)


@router.get("/{food_id}", response_model=FoodRead)
async def get_food(food_id: UUID, service: CatalogServiceDep, include_inactive: bool = False):
    return await service.get(FoodItem, food_id, include_inactive=include_inactive)


@router.patch("/{food_id}", response_model=FoodRead)
@transaction
async def update_food(food_id: UUID, payload: FoodUpdateRequest, service: CatalogServiceDep):
    return await service.update(FoodItem, food_id, payload)


@router.delete("/{food_id}", status_code=204)
@transaction
async def delete_food(food_id: UUID, expected_version_id: VersionQuery, service: CatalogServiceDep):
    await service.set_active(FoodItem, food_id, expected_version_id, active=False)
    return Response(status_code=204)


@router.post("/{food_id}/restore", response_model=FoodRead)
@transaction
async def restore_food(food_id: UUID, payload: VersionedRequest, service: CatalogServiceDep):
    return await service.set_active(FoodItem, food_id, payload.expected_version_id, active=True)

