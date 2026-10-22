"""Authentication router for Google OAuth login, refresh token, and logout."""

from fastapi import APIRouter, Cookie, HTTPException, Query, Request

from core.database import transaction
from core.security import (
    BearerCredentials,
    RefreshTokenCookie,
    STATE_COOKIE_NAME,
    decode_access_token,
)
from core.settings import settings
from schemas.auth_session import LogoutResponse
from services.auth_service import AuthService, AuthServiceDep

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
    request: Request,
    refresh_token: RefreshTokenCookie,
    auth_service: AuthServiceDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    redirect_uri: str | None = Query(default=None),
    oauth_state: str | None = Cookie(default=None, alias=STATE_COOKIE_NAME),
    oauth_redirect_uri: str | None = Cookie(
        default=None, alias=AuthService.REDIRECT_URI_COOKIE_NAME
    ),
):
    referer = request.headers.get("referer")
    if (code is None) != (state is None):
        raise HTTPException(400, "OAuth code and state must be supplied together")
    if code and state:
        accept = request.headers.get("accept", "")
        is_browser_nav = "text/html" in accept and "application/json" not in accept
        resolved_redirect = settings.resolve_oauth_redirect_uri(
            redirect_uri or oauth_redirect_uri,
            referer=referer,
        )
        return await auth_service.handle_google_callback(
            code,
            state,
            oauth_state,
            redirect_uri=resolved_redirect,
            redirect_to_frontend=is_browser_nav,
        )

    if mode == "oauth":
        resolved_redirect = settings.resolve_oauth_redirect_uri(
            redirect_uri,
            referer=referer,
        )
        return await auth_service.refresh_with_cookie(
            None,
            redirect_uri=resolved_redirect,
        )
    if mode == "refresh" and not refresh_token:
        raise HTTPException(401, "Missing refresh token")

    resolved_redirect = (
        settings.resolve_oauth_redirect_uri(redirect_uri, referer=referer)
        if not refresh_token
        else None
    )
    return await auth_service.refresh_with_cookie(
        refresh_token,
        redirect_uri=resolved_redirect,
    )


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
    decode_access_token(_credentials.credentials)
    return await auth_service.logout(refresh_token)

