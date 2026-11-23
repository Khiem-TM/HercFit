"""Đăng ký API v1/v2 và các endpoint xem trước trong savepoint được rollback."""

from uuid import UUID

from fastapi import APIRouter

from agentic.embedding.retrieval.router import router as embedding_router
from api.dependencies import JournalServiceDep, PlanServiceDep
from domains.analytics.routers import (
    assistant_router,
    context_router,
    dashboard_router,
    progress_router,
)
from domains.body.routers import body_metrics_router
from domains.catalog.routers import exercise_router, food_router
from domains.goals_plans.models import TrainingPlan
from domains.goals_plans.routers import goal_router, plan_router, training_plan_router
from domains.goals_plans.schemas import TrainingPlanCreate, TrainingPlanRead, TrainingPlanReplace
from domains.health_records.routers import health_router, health_v2_router
from domains.identity.routers import auth_router, delegation_router, privacy_router, profile_router
from domains.media.routers import media_router
from domains.notifications.routers import notifications_router
from domains.nutrition.models import Meal
from domains.nutrition.routers import meal_router, nutrition_router
from domains.nutrition.schemas import MealCreate, MealRead
from domains.shared.services import require_found
from domains.training.models import Training
from domains.training.routers import training_analytics_router, training_router
from domains.training.schemas import TrainingCreate, TrainingRead
from integrations.google_health.router import records_router as google_health_records_router
from integrations.google_health.router import router as integration_router

_preview_router = APIRouter(tags=["previews"])


async def _dry_run(session, build, read_schema):
    # Serialize khi entity còn trong savepoint; rollback cả dữ liệu con và graph outbox.
    savepoint = await session.begin_nested()
    try:
        entity = await build()
        return {"preview": True, **read_schema.model_validate(entity).model_dump(mode="json")}
    finally:
        await savepoint.rollback()


@_preview_router.post("/meals/preview")
async def preview_meal(payload: MealCreate, service: JournalServiceDep):
    return await _dry_run(
        service.session,
        lambda: Meal.create_snapshot(service.session, user_id=service.user_id, payload=payload),
        MealRead,
    )


@_preview_router.post("/trainings/preview")
async def preview_training(payload: TrainingCreate, service: JournalServiceDep):
    return await _dry_run(
        service.session,
        lambda: Training.create_snapshot(service.session, user_id=service.user_id, payload=payload),
        TrainingRead,
    )


@_preview_router.post("/training-plans/preview")
async def preview_current_training_plan(payload: TrainingPlanCreate, service: PlanServiceDep):
    return await _dry_run(
        service.session,
        lambda: TrainingPlan.create_with_parent(
            service.session, user_id=service.user_id, payload=payload,
        ),
        TrainingPlanRead,
    )


@_preview_router.post("/training-plans/{training_plan_id}/preview")
async def preview_training_plan_replacement(
    training_plan_id: UUID, payload: TrainingPlanReplace, service: PlanServiceDep,
):
    async def build():
        return require_found(
            await TrainingPlan.replace_for_user(
                service.session, training_plan_id, user_id=service.user_id, payload=payload,
                expected_version_id=payload.expected_version_id,
            ),
            "TrainingPlan",
        )

    return await _dry_run(service.session, build, TrainingPlanRead)


api_router = APIRouter(prefix="/api")

for domain_router in (
    delegation_router, health_v2_router, google_health_records_router,
    context_router, notifications_router,
):
    api_router.include_router(domain_router, prefix="/v2")

# Privacy trước profile, preview trước các router nhận ID để giữ thứ tự khớp route.
for domain_router in (
    auth_router, privacy_router, profile_router, body_metrics_router, goal_router, media_router,
    _preview_router, food_router, exercise_router, plan_router, training_plan_router,
    meal_router, training_router, progress_router, dashboard_router, training_analytics_router, nutrition_router,
    integration_router, health_router, assistant_router,
):
    api_router.include_router(domain_router)

api_router.include_router(embedding_router)

__all__ = ["api_router"]
