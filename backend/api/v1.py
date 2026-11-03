"""Router API tập trung, gom router của mọi miền."""

from fastapi import APIRouter, Depends

from domains.identity.routers.auth_router import limit_auth, login, logout, router as auth_router
from domains.body.routers.body_metrics_router import router as body_metrics_router
from domains.goals_plans.routers.goal_router import router as goal_router
from domains.identity.routers.profile_router import router as profile_router
from domains.catalog.routers.food_router import router as food_router
from domains.catalog.routers.exercise_router import router as exercise_router
from domains.goals_plans.routers.plan_router import router as plan_router
from domains.goals_plans.routers.training_plan_router import router as training_plan_router
from domains.nutrition.routers.meal_router import router as meal_router
from domains.training.routers.training_router import router as training_router
from domains.analytics.routers.progress_router import router as progress_router
from domains.training.routers.training_analytics_router import router as training_analytics_router
from api.preview_router import router as preview_router
from domains.media.routers.media_router import router as media_router
from domains.nutrition.routers.nutrition_router import router as nutrition_router
from domains.identity.routers.privacy_router import router as privacy_router
from integrations.google_health.router import router as integration_router
from domains.health_records.routers.health_router import router as health_router
from domains.analytics.routers.assistant_router import router as assistant_router
from domains.identity.schemas.auth_session import LogoutResponse

api_router = APIRouter()
api_router.include_router(auth_router)
# Đặt trước profile_router để /profile/export và /profile/erase được khớp trước.
api_router.include_router(privacy_router)
api_router.include_router(profile_router)
api_router.include_router(body_metrics_router)
api_router.include_router(goal_router)
api_router.include_router(media_router)
for domain_router in (preview_router, food_router, exercise_router, plan_router,
                      training_plan_router, meal_router, training_router, progress_router,
                      training_analytics_router, nutrition_router, integration_router, health_router, assistant_router):
    api_router.include_router(domain_router)

# Route bí danh: /api/login và /api/logout
alias_router = APIRouter(tags=["auth"], dependencies=[Depends(limit_auth)])
alias_router.add_api_route(
    "/login",
    login,
    methods=["GET"],
    summary="Đăng nhập hoặc làm mới phiên đăng nhập (Alias)",
    include_in_schema=False,
)
alias_router.add_api_route(
    "/logout",
    logout,
    methods=["POST"],
    response_model=LogoutResponse,
    summary="Đăng xuất (Alias)",
    include_in_schema=False,
)
api_router.include_router(alias_router)

__all__ = ["api_router", "auth_router"]
