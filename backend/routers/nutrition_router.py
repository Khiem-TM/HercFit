"""Deterministic daily energy and macro targets with an adaptive expenditure estimate."""
from typing import Annotated

from fastapi import APIRouter, Query

from routers.dependencies import service_dependency
from schemas.nutrition import NutritionTargetsRead
from schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName
from services.nutrition_targets import NutritionTargetService

router = APIRouter(prefix="/nutrition", tags=["nutrition"])
NutritionTargetServiceDep = Annotated[NutritionTargetService, service_dependency(NutritionTargetService)]


@router.get(
    "/targets",
    response_model=NutritionTargetsRead,
    summary="Mục tiêu năng lượng và macro trong ngày",
    description="BMR (Mifflin-St Jeor), TDEE, mục tiêu theo goal hiện tại với giới hạn an toàn, macro, "
                "cân nặng xu hướng và ước lượng chi tiêu thích ứng từ nhật ký 28 ngày.",
)
async def get_targets(service: NutritionTargetServiceDep,
                      timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    return await service.targets(timezone=timezone)
