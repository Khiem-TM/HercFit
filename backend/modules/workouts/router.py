"""FastAPI router for Workouts CRUD endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from core.database import get_db
from core.security import get_current_user_id
from modules.workouts import service as workouts_service
from modules.workouts.schemas import (
    WorkoutPlanCreate,
    WorkoutPlanResponse,
    WorkoutSessionCreate,
    WorkoutSessionResponse,
)

router = APIRouter()


@router.post("/plans", response_model=WorkoutPlanResponse)
async def create_plan(
    payload: WorkoutPlanCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> WorkoutPlanResponse:
    return await workouts_service.create_workout_plan(db, user_id, payload)


@router.get("/plans", response_model=list[WorkoutPlanResponse])
async def get_plans(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> list[WorkoutPlanResponse]:
    return await workouts_service.list_workout_plans(db, user_id)


@router.post("/sessions", response_model=WorkoutSessionResponse)
async def create_session(
    payload: WorkoutSessionCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> WorkoutSessionResponse:
    return await workouts_service.log_workout_session(db, user_id, payload)


@router.get("/sessions", response_model=list[WorkoutSessionResponse])
async def get_sessions(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
    limit: int = 10,
) -> list[WorkoutSessionResponse]:
    return await workouts_service.list_workout_sessions(db, user_id, limit=limit)
