"""FastAPI router for Nutrition CRUD endpoints."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from core.database import get_db
from core.security import get_current_user_id
from modules.nutrition import service as nutrition_service
from modules.nutrition.schemas import DailyNutritionSummary, MealCreate, MealResponse

router = APIRouter()


@router.post("/meals", response_model=MealResponse)
async def create_meal(
    payload: MealCreate,
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
) -> MealResponse:
    return await nutrition_service.log_meal(db, user_id, payload)


@router.get("/summary", response_model=DailyNutritionSummary)
async def get_summary(
    user_id: Annotated[str, Depends(get_current_user_id)],
    db: Annotated[Any, Depends(get_db)],
    target_date: date | None = None,
) -> DailyNutritionSummary:
    return await nutrition_service.get_daily_nutrition_summary(
        db, user_id, target_date=target_date
    )
