"""Presentation Layer (Router) for User Profile and Body Metrics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user_id
from schemas.user import (
    BodyMetricCreate,
    BodyMetricResponse,
    UserProfileResponse,
    UserProfileUpdate,
)
from services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


def get_user_service(db: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    return UserService(db)


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    return await service.get_user_profile(user_id)


@router.patch("/profile", response_model=UserProfileResponse)
async def update_profile(
    payload: UserProfileUpdate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    return await service.update_user_profile(user_id, payload)


@router.post("/metrics", response_model=BodyMetricResponse)
async def create_body_metric(
    payload: BodyMetricCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> BodyMetricResponse:
    return await service.log_body_metric(user_id, payload)


@router.get("/metrics", response_model=list[BodyMetricResponse])
async def get_body_metrics(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[UserService, Depends(get_user_service)],
    limit: int = 10,
) -> list[BodyMetricResponse]:
    return await service.list_body_metrics(user_id, limit=limit)

