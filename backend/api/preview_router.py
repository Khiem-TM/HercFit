"""Xem trước kiểu chạy thử cho thẻ xác nhận: tính chính xác những gì lệnh ghi sẽ lưu, rồi rollback."""
from uuid import UUID

from fastapi import APIRouter

from domains.nutrition.models.meals import Meal
from domains.training.models.trainings import Training
from domains.goals_plans.models.plans import TrainingPlan
from api.dependencies import JournalServiceDep, PlanServiceDep
from domains.nutrition.schemas.meals import MealCreate, MealRead
from domains.training.schemas.trainings import TrainingCreate, TrainingRead
from domains.goals_plans.schemas.plans import TrainingPlanCreate, TrainingPlanRead

router = APIRouter(tags=["previews"])


async def _dry_run(session, build, read_schema):
    # Cùng bước kiểm tra, ảnh chụp catalog, tổng và chỉ số như lệnh ghi thật;
    # savepoint (kể cả các dòng graph outbox) luôn bị bỏ.
    savepoint = await session.begin_nested()
    try:
        entity = await build()
        return {"preview": True, **read_schema.model_validate(entity).model_dump(mode="json")}
    finally:
        await savepoint.rollback()


@router.post("/meals/preview")
async def preview_meal(payload: MealCreate, service: JournalServiceDep):
    return await _dry_run(service.session, lambda: Meal.create_snapshot(service.session, user_id=service.user_id, payload=payload), MealRead)


@router.post("/trainings/preview")
async def preview_training(payload: TrainingCreate, service: JournalServiceDep):
    return await _dry_run(service.session, lambda: Training.create_snapshot(service.session, user_id=service.user_id, payload=payload), TrainingRead)


@router.post("/plans/{plan_id}/training-plans/preview")
async def preview_training_plan(plan_id: UUID, payload: TrainingPlanCreate, service: PlanServiceDep):
    return await _dry_run(service.session, lambda: TrainingPlan.create_for_user(service.session, user_id=service.user_id, plan_id=plan_id, payload=payload),
                          TrainingPlanRead)
