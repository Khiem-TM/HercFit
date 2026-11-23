"""Router HTTP của miền catalog thực phẩm và bài tập."""

from uuid import UUID

from fastapi import APIRouter, Response

from agentic.research.contracts import (
    ExerciseFinalization,
    ExerciseFinalizationResult,
    FoodFinalization,
    FoodFinalizationResult,
)
from api.dependencies import CatalogServiceDep, ExerciseQueryDep, FoodQueryDep, VersionQuery
from api.responses import created
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.catalog.models import Exercise, FoodItem
from domains.catalog.schemas import (
    ExerciseCreate,
    ExerciseRead,
    ExerciseUpdateRequest,
    FoodCreate,
    FoodRead,
    FoodUpdateRequest,
)
from domains.shared.schemas import VersionedRequest

# --------------------------------------------------------------------------------------------------
# Các endpoint danh mục bài tập cá nhân.
# --------------------------------------------------------------------------------------------------

exercise_router = APIRouter(route_class=IdempotentRoute, prefix="/exercises", tags=["exercises"])


@exercise_router.post("", response_model=ExerciseRead, status_code=201)
@transaction
async def create_exercise(payload: ExerciseCreate, service: CatalogServiceDep, response: Response):
    return created(response, "exercises", await service.create(Exercise, payload))


@exercise_router.get("", response_model=list[ExerciseRead])
async def list_exercises(options: ExerciseQueryDep, service: CatalogServiceDep):
    return await service.list(Exercise, options)


@exercise_router.get("/resolve")
async def resolve_exercise(service: CatalogServiceDep, query: str):
    from agentic.research.contracts import ResolveQuery
    from domains.catalog.services import resolve
    return await resolve(service, 'exercises', ResolveQuery(query=query).query)



# Route idempotent lưu phản hồi đã kiểm tra, nên kết quả cần một response model.
@exercise_router.post("/research-finalizations", response_model=ExerciseFinalizationResult)
@transaction
async def finalize_exercise(payload: ExerciseFinalization, service: CatalogServiceDep):
    from domains.catalog.services import finalize
    return await finalize(service, 'exercises', payload)


@exercise_router.get("/{exercise_id}", response_model=ExerciseRead)
async def get_exercise(exercise_id: UUID, service: CatalogServiceDep, include_inactive: bool = False):
    return await service.get(Exercise, exercise_id, include_inactive=include_inactive)


@exercise_router.patch("/{exercise_id}", response_model=ExerciseRead)
@transaction
async def update_exercise(exercise_id: UUID, payload: ExerciseUpdateRequest, service: CatalogServiceDep):
    return await service.update(Exercise, exercise_id, payload)


@exercise_router.delete("/{exercise_id}", status_code=204)
@transaction
async def delete_exercise(exercise_id: UUID, expected_version_id: VersionQuery, service: CatalogServiceDep):
    await service.set_active(Exercise, exercise_id, expected_version_id, active=False)
    return Response(status_code=204)


@exercise_router.post("/{exercise_id}/restore", response_model=ExerciseRead)
@transaction
async def restore_exercise(exercise_id: UUID, payload: VersionedRequest, service: CatalogServiceDep):
    return await service.set_active(Exercise, exercise_id, payload.expected_version_id, active=True)


# --------------------------------------------------------------------------------------------------
# Các endpoint danh mục thực phẩm cá nhân.
# --------------------------------------------------------------------------------------------------

food_router = APIRouter(route_class=IdempotentRoute, prefix="/foods", tags=["foods"])


@food_router.post("", response_model=FoodRead, status_code=201)
@transaction
async def create_food(payload: FoodCreate, service: CatalogServiceDep, response: Response):
    return created(response, "foods", await service.create(FoodItem, payload))


@food_router.get("", response_model=list[FoodRead])
async def list_foods(options: FoodQueryDep, service: CatalogServiceDep):
    return await service.list(FoodItem, options)


@food_router.get("/resolve")
async def resolve_food(service: CatalogServiceDep, query: str):
    from agentic.research.contracts import ResolveQuery
    from domains.catalog.services import resolve
    return await resolve(service, 'foods', ResolveQuery(query=query).query)



# Route idempotent lưu phản hồi đã kiểm tra, nên kết quả cần một response model.
@food_router.post("/research-finalizations", response_model=FoodFinalizationResult)
@transaction
async def finalize_food(payload: FoodFinalization, service: CatalogServiceDep):
    from domains.catalog.services import finalize
    return await finalize(service, 'foods', payload)


@food_router.get("/{food_id}", response_model=FoodRead)
async def get_food(food_id: UUID, service: CatalogServiceDep, include_inactive: bool = False):
    return await service.get(FoodItem, food_id, include_inactive=include_inactive)


@food_router.patch("/{food_id}", response_model=FoodRead)
@transaction
async def update_food(food_id: UUID, payload: FoodUpdateRequest, service: CatalogServiceDep):
    return await service.update(FoodItem, food_id, payload)


@food_router.delete("/{food_id}", status_code=204)
@transaction
async def delete_food(food_id: UUID, expected_version_id: VersionQuery, service: CatalogServiceDep):
    await service.set_active(FoodItem, food_id, expected_version_id, active=False)
    return Response(status_code=204)


@food_router.post("/{food_id}/restore", response_model=FoodRead)
@transaction
async def restore_food(food_id: UUID, payload: VersionedRequest, service: CatalogServiceDep):
    return await service.set_active(FoodItem, food_id, payload.expected_version_id, active=True)
