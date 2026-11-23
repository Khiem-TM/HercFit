"""Router HTTP của miền dinh dưỡng."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from api.dependencies import JournalQueryDep, JournalServiceDep, VersionQuery, service_dependency
from api.responses import created
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.nutrition.models import Meal
from domains.nutrition.schemas import MealCreate, MealRead, MealReplace, NutritionTargetsRead
from domains.nutrition.services import NutritionTargetService
from domains.shared.schemas import DEFAULT_TIMEZONE, TimeZoneName

# --------------------------------------------------------------------------------------------------
# Bữa ăn thực tế: ảnh chụp bất biến đầy đủ.
# --------------------------------------------------------------------------------------------------

meal_router = APIRouter(route_class=IdempotentRoute, prefix="/meals", tags=["meals"])


@meal_router.post("", response_model=MealRead, status_code=201)
@transaction
async def create_meal(payload: MealCreate, service: JournalServiceDep, response: Response):
    return created(response, "meals", await service.create(Meal, payload))


@meal_router.get("", response_model=list[MealRead])
async def list_meals(options: JournalQueryDep, service: JournalServiceDep):
    return await service.list(Meal, options)


@meal_router.get("/{meal_id}", response_model=MealRead)
async def get_meal(meal_id: UUID, service: JournalServiceDep, include_inactive: bool = False):
    return await service.get(Meal, meal_id, include_inactive=include_inactive)


@meal_router.put("/{meal_id}", response_model=MealRead, status_code=201)
@transaction
async def replace_meal(meal_id: UUID, payload: MealReplace, service: JournalServiceDep, response: Response):
    return created(response, "meals", await service.replace(Meal, meal_id, payload))


@meal_router.delete("/{meal_id}", status_code=204)
@transaction
async def delete_meal(meal_id: UUID, expected_version_id: VersionQuery, service: JournalServiceDep):
    await service.delete(Meal, meal_id, expected_version_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------------------------------
# Mục tiêu năng lượng và macro theo ngày tất định, kèm ước tính mức tiêu hao thích ứng.
# --------------------------------------------------------------------------------------------------

nutrition_router = APIRouter(prefix="/nutrition", tags=["nutrition"])
NutritionTargetServiceDep = Annotated[NutritionTargetService, service_dependency(NutritionTargetService)]


@nutrition_router.get(
    "/targets",
    response_model=NutritionTargetsRead,
    summary="Mục tiêu năng lượng và macro trong ngày",
    description="BMR (Mifflin-St Jeor), TDEE, mục tiêu theo goal hiện tại với giới hạn an toàn, macro, "
                "cân nặng xu hướng và ước lượng chi tiêu thích ứng từ nhật ký 28 ngày.",
)
async def get_targets(service: NutritionTargetServiceDep,
                      timezone: Annotated[TimeZoneName, Query()] = DEFAULT_TIMEZONE):
    return await service.targets(timezone=timezone)
