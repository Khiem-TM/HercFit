"""Dry-run previews for confirmation cards: compute exactly what a write would store, then roll back."""
from uuid import UUID

from fastapi import APIRouter

from models.journals import Meal, Training
from models.plans import TrainingPlan
from routers.dependencies import JournalServiceDep, PlanServiceDep
from schemas.journals import MealCreate, MealRead, TrainingCreate, TrainingRead
from schemas.plans import TrainingPlanCreate, TrainingPlanRead

router = APIRouter(tags=["previews"])


async def _dry_run(session, build, read_schema):
    # Same validation, catalog snapshots, totals and metrics as the real write;
    # the savepoint (including graph outbox rows) is always discarded.
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
