"""Xem trước kiểu chạy thử cho thẻ xác nhận: tính chính xác những gì lệnh ghi sẽ lưu, rồi rollback."""
from uuid import UUID

from fastapi import APIRouter

from api.dependencies import JournalServiceDep, PlanServiceDep
from domains.goals_plans.models.plans import TrainingPlan
from domains.goals_plans.schemas.plans import (
    TrainingPlanCreate,
    TrainingPlanRead,
    TrainingPlanReplace,
)
from domains.nutrition.models.meals import Meal
from domains.nutrition.schemas.meals import MealCreate, MealRead
from domains.shared.services.common import require_found
from domains.training.models.trainings import Training
from domains.training.schemas.trainings import TrainingCreate, TrainingRead

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


@router.post("/training-plans/preview")
async def preview_current_training_plan(payload: TrainingPlanCreate, service: PlanServiceDep):
    return await _dry_run(service.session, lambda: TrainingPlan.create_with_parent(service.session, user_id=service.user_id, payload=payload),
                          TrainingPlanRead)


@router.post("/training-plans/{training_plan_id}/preview")
async def preview_training_plan_replacement(training_plan_id: UUID, payload: TrainingPlanReplace, service: PlanServiceDep):
    async def build():
        return require_found(await TrainingPlan.replace_for_user(
            service.session, training_plan_id, user_id=service.user_id, payload=payload,
            expected_version_id=payload.expected_version_id), "TrainingPlan")
    return await _dry_run(service.session, build, TrainingPlanRead)
