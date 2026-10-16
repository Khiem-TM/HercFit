"""FastAPI router for User Profile and Body Metrics CRUD endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from core.database import get_db
from core.security import get_current_user_id
from modules.users import service as users_service
from modules.users.schemas import (
    BodyMetricCreate,
    BodyMetricResponse,
    UserProfileResponse,
    UserProfileUpdate,
)

router = APIRouter()


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> UserProfileResponse:
    return await users_service.get_user_profile(db, user_id)


@router.patch("/profile", response_model=UserProfileResponse)
async def update_profile(
    payload: UserProfileUpdate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> UserProfileResponse:
    return await users_service.update_user_profile(db, user_id, payload)


@router.post("/metrics", response_model=BodyMetricResponse)
async def create_body_metric(
    payload: BodyMetricCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> BodyMetricResponse:
    return await users_service.log_body_metric(db, user_id, payload)


@router.get("/metrics", response_model=list[BodyMetricResponse])
async def get_body_metrics(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
    limit: int = 10,
) -> list[BodyMetricResponse]:
    return await users_service.list_body_metrics(db, user_id, limit=limit)
