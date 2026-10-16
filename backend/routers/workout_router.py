"""Presentation Layer (Router) for Workout Plans and Workout Sessions endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user_id
from schemas.workout import (
    WorkoutPlanCreate,
    WorkoutPlanResponse,
    WorkoutSessionCreate,
    WorkoutSessionResponse,
)
from services.workout_service import WorkoutService

router = APIRouter(prefix="/workouts", tags=["Workouts"])


def get_workout_service(db: Annotated[AsyncSession, Depends(get_db)]) -> WorkoutService:
    return WorkoutService(db)


@router.post("/plans", response_model=WorkoutPlanResponse)
async def create_plan(
    payload: WorkoutPlanCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[WorkoutService, Depends(get_workout_service)],
) -> WorkoutPlanResponse:
    return await service.create_workout_plan(user_id, payload)


@router.get("/plans", response_model=list[WorkoutPlanResponse])
async def get_plans(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[WorkoutService, Depends(get_workout_service)],
) -> list[WorkoutPlanResponse]:
    return await service.list_workout_plans(user_id)


@router.post("/sessions", response_model=WorkoutSessionResponse)
async def create_session(
    payload: WorkoutSessionCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[WorkoutService, Depends(get_workout_service)],
) -> WorkoutSessionResponse:
    return await service.log_workout_session(user_id, payload)


@router.get("/sessions", response_model=list[WorkoutSessionResponse])
async def get_sessions(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[WorkoutService, Depends(get_workout_service)],
    limit: int = 10,
) -> list[WorkoutSessionResponse]:
    return await service.list_workout_sessions(user_id, limit=limit)

