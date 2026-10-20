"""Centralized API router aggregating all domain routers."""

from fastapi import APIRouter

from routers.auth_router import login, logout, router as auth_router
from routers.body_metrics_router import router as body_metrics_router
from routers.goal_router import router as goal_router
from routers.profile_router import router as profile_router
from routers.food_router import router as food_router
from routers.exercise_router import router as exercise_router
from routers.plan_router import router as plan_router
from routers.meal_plan_router import router as meal_plan_router
from routers.training_plan_router import router as training_plan_router
from routers.meal_router import router as meal_router
from routers.training_router import router as training_router
from routers.progress_router import router as progress_router
from schemas.auth_session import LogoutResponse

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(profile_router)
api_router.include_router(body_metrics_router)
api_router.include_router(goal_router)
for domain_router in (food_router, exercise_router, plan_router, meal_plan_router,
                      training_plan_router, meal_router, training_router, progress_router):
    api_router.include_router(domain_router)

# Alias routes: /api/login and /api/logout
alias_router = APIRouter(tags=["auth"])
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
