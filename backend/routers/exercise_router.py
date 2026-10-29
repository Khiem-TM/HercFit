"""Personal exercises catalog endpoints."""
from uuid import UUID

from fastapi import APIRouter, Response
from core.transaction import transaction
from core.idempotency import IdempotentRoute
from models.exercises import Exercise
from schemas.exercises import ExerciseCreate, ExerciseRead, ExerciseUpdateRequest
from schemas.tracking import VersionedRequest
from routers.dependencies import CatalogServiceDep, ExerciseQueryDep, VersionQuery
from routers.responses import created

router = APIRouter(route_class=IdempotentRoute, prefix="/exercises", tags=["exercises"])


@router.post("", response_model=ExerciseRead, status_code=201)
@transaction
async def create_exercise(payload: ExerciseCreate, service: CatalogServiceDep, response: Response):
    return created(response, "exercises", await service.create(Exercise, payload))


@router.get("", response_model=list[ExerciseRead])
async def list_exercises(options: ExerciseQueryDep, service: CatalogServiceDep):
    return await service.list(Exercise, options)


@router.get("/resolve")
async def resolve_exercise(service: CatalogServiceDep, query: str):
    from research.contracts import ResolveQuery
    from services.research_catalog import resolve
    return await resolve(service, 'exercises', ResolveQuery(query=query).query)


from research.contracts import ExerciseFinalization, ExerciseFinalizationResult

# The idempotent route stores the validated response, so the result needs a response model.
@router.post("/research-finalizations", response_model=ExerciseFinalizationResult)
@transaction
async def finalize_exercise(payload: ExerciseFinalization, service: CatalogServiceDep):
    from services.research_catalog import finalize
    return await finalize(service, 'exercises', payload)


@router.get("/{exercise_id}", response_model=ExerciseRead)
async def get_exercise(exercise_id: UUID, service: CatalogServiceDep, include_inactive: bool = False):
    return await service.get(Exercise, exercise_id, include_inactive=include_inactive)


@router.patch("/{exercise_id}", response_model=ExerciseRead)
@transaction
async def update_exercise(exercise_id: UUID, payload: ExerciseUpdateRequest, service: CatalogServiceDep):
    return await service.update(Exercise, exercise_id, payload)


@router.delete("/{exercise_id}", status_code=204)
@transaction
async def delete_exercise(exercise_id: UUID, expected_version_id: VersionQuery, service: CatalogServiceDep):
    await service.set_active(Exercise, exercise_id, expected_version_id, active=False)
    return Response(status_code=204)


@router.post("/{exercise_id}/restore", response_model=ExerciseRead)
@transaction
async def restore_exercise(exercise_id: UUID, payload: VersionedRequest, service: CatalogServiceDep):
    return await service.set_active(Exercise, exercise_id, payload.expected_version_id, active=True)

