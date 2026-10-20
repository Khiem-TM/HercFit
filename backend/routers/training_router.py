"""Actual trainings: complete immutable snapshots."""
from uuid import UUID

from fastapi import APIRouter, Response
from core.transaction import transaction
from models.journals import Training
from schemas.journals import TrainingCreate, TrainingReplace, TrainingRead
from routers.dependencies import JournalServiceDep, JournalQueryDep, VersionQuery
from routers.responses import created

router = APIRouter(prefix="/trainings", tags=["trainings"])


@router.post("", response_model=TrainingRead, status_code=201)
@transaction
async def create_training(payload: TrainingCreate, service: JournalServiceDep, response: Response):
    return created(response, "trainings", await service.create(Training, payload))


@router.get("", response_model=list[TrainingRead])
async def list_trainings(options: JournalQueryDep, service: JournalServiceDep):
    return await service.list(Training, options)


@router.get("/{training_id}", response_model=TrainingRead)
async def get_training(training_id: UUID, service: JournalServiceDep, include_inactive: bool = False):
    return await service.get(Training, training_id, include_inactive=include_inactive)


@router.put("/{training_id}", response_model=TrainingRead, status_code=201)
@transaction
async def replace_training(training_id: UUID, payload: TrainingReplace, service: JournalServiceDep, response: Response):
    return created(response, "trainings", await service.replace(Training, training_id, payload))


@router.delete("/{training_id}", status_code=204)
@transaction
async def delete_training(training_id: UUID, expected_version_id: VersionQuery, service: JournalServiceDep):
    await service.delete(Training, training_id, expected_version_id)
    return Response(status_code=204)

