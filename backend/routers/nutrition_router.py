"""Presentation Layer (Router) for Nutrition and Meals endpoints."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user_id
from schemas.nutrition import DailyNutritionSummary, MealCreate, MealResponse
from services.nutrition_service import NutritionService

router = APIRouter(prefix="/nutrition", tags=["Nutrition"])


def get_nutrition_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NutritionService:
    return NutritionService(db)


@router.post("/meals", response_model=MealResponse)
async def create_meal(
    payload: MealCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[NutritionService, Depends(get_nutrition_service)],
) -> MealResponse:
    return await service.log_meal(user_id, payload)


@router.get("/summary", response_model=DailyNutritionSummary)
async def get_summary(
    user_id: Annotated[str, Depends(get_current_user_id)],
    service: Annotated[NutritionService, Depends(get_nutrition_service)],
    target_date: date | None = None,
) -> DailyNutritionSummary:
    return await service.get_daily_nutrition_summary(user_id, target_date=target_date)

