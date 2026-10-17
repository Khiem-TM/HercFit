"""Authentication router for Google OAuth login, refresh token, and logout."""

from fastapi import APIRouter, Cookie, Query

from core.database import transaction
from core.security import (
    BearerCredentials,
    RefreshTokenCookie,
    STATE_COOKIE_NAME,
)
from schemas.auth_session import LogoutResponse
from services.auth_service import AuthServiceDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/login",
    summary="Đăng nhập hoặc làm mới phiên đăng nhập",
    description=(
        "Bắt đầu Google OAuth, xử lý callback OAuth hoặc làm mới access token "
    ),
)
@transaction
async def login(
    refresh_token: RefreshTokenCookie,
    auth_service: AuthServiceDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    oauth_state: str | None = Cookie(default=None, alias=STATE_COOKIE_NAME),
):
    if code and state:
        return await auth_service.handle_google_callback(code, state, oauth_state)

    return await auth_service.refresh_with_cookie(refresh_token)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Đăng xuất",
    description="Thu hồi refresh session và xóa refresh-token cookie.",
)
@transaction
async def logout(
    refresh_token: RefreshTokenCookie,
    auth_service: AuthServiceDep,
    _credentials: BearerCredentials,
):
    return await auth_service.logout(refresh_token)

