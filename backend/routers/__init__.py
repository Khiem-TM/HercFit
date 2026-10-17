"""Centralized API router aggregating all domain routers."""

from fastapi import APIRouter

from routers.auth_router import login, logout, router as auth_router
from schemas.auth_session import LogoutResponse

api_router = APIRouter()
api_router.include_router(auth_router)

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
