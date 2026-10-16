"""Presentation Layer (Router) for Habits and Daily Check-ins endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user_id
from schemas.habit import (
    HabitCheckInCreate,
    HabitCheckInResponse,
    HabitCreate,
    HabitResponse,
)
from services.habit_service import HabitService

router = APIRouter(prefix="/habits", tags=["Habits"])


def get_habit_service(db: Annotated[AsyncSession, Depends(get_db)]) -> HabitService:
    return HabitService(db)


@router.post("", response_model=HabitResponse)
async def create_habit(
    payload: HabitCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[HabitService, Depends(get_habit_service)],
) -> HabitResponse:
    return await service.create_habit(user_id, payload)


@router.get("", response_model=list[HabitResponse])
async def get_habits(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[HabitService, Depends(get_habit_service)],
) -> list[HabitResponse]:
    return await service.list_habits(user_id)


@router.post("/{habit_id}/checkins", response_model=HabitCheckInResponse)
async def check_in_habit(
    habit_id: str,
    payload: HabitCheckInCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[HabitService, Depends(get_habit_service)],
) -> HabitCheckInResponse:
    return await service.check_in_habit(user_id, habit_id, payload)


@router.get("/checkins", response_model=list[HabitCheckInResponse])
async def get_daily_checkins(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[HabitService, Depends(get_habit_service)],
    target_date: date | None = None,
) -> list[HabitCheckInResponse]:
    return await service.list_daily_checkins(user_id, target_date=target_date)

