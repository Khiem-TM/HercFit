"""Router xác thực: Google OAuth (PKCE), xoay refresh token và đăng xuất."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request

from core.rate_limit import SlidingWindowLimiter, client_key, enforce
from core.security import (
    PKCE_COOKIE_NAME,
    STATE_COOKIE_NAME,
    BearerCredentials,
    RefreshTokenCookie,
    decode_access_token,
)
from core.settings import settings
from core.transaction import transaction
from domains.identity.schemas.auth_session import LogoutResponse
from domains.identity.services.auth_service import AuthService, AuthServiceDep

_limiter = SlidingWindowLimiter(settings.AUTH_RATE_LIMIT_PER_MINUTE)


def limit_auth(request: Request) -> None:
    enforce(_limiter, client_key(request))


def same_origin(request: Request) -> None:
    """POST xác thực bằng cookie phải đến từ origin trình duyệt được phép (CSRF); thiếu header Origin cũng bị từ chối."""
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in {o.rstrip("/") for o in [*settings.CORS_ORIGINS, settings.FRONTEND_URL]}:
        raise HTTPException(403, "Origin is not allowed")


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(limit_auth)])


@router.get(
    "/login",
    summary="Đăng nhập Google OAuth",
    description="Bắt đầu Google OAuth (PKCE, mode=oauth) hoặc xử lý callback (code, state). Làm mới phiên: POST /auth/refresh.",
)
@transaction
async def login(
    request: Request,
    auth_service: AuthServiceDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    redirect_uri: str | None = Query(default=None),
    oauth_state: str | None = Cookie(default=None, alias=STATE_COOKIE_NAME),
    oauth_pkce: str | None = Cookie(default=None, alias=PKCE_COOKIE_NAME),
    oauth_redirect_uri: str | None = Cookie(default=None, alias=AuthService.REDIRECT_URI_COOKIE_NAME),
):
    referer = request.headers.get("referer")
    if (code is None) != (state is None):
        raise HTTPException(400, "OAuth code and state must be supplied together")
    if code and state:
        accept = request.headers.get("accept", "")
        is_browser_nav = "text/html" in accept and "application/json" not in accept
        resolved_redirect = settings.resolve_oauth_redirect_uri(redirect_uri or oauth_redirect_uri, referer=referer)
        return await auth_service.handle_google_callback(
            code, state, oauth_state, redirect_uri=resolved_redirect,
            redirect_to_frontend=is_browser_nav, code_verifier=oauth_pkce,
        )
    if mode == "oauth":
        return auth_service.start_google_login(settings.resolve_oauth_redirect_uri(redirect_uri, referer=referer))
    # GET không làm mới phiên bằng cookie (CSRF): chỉ POST /auth/refresh, có kiểm tra Origin.
    raise HTTPException(400, "Use mode=oauth to sign in or POST /auth/refresh to renew the session")


@router.post(
    "/refresh",
    summary="Làm mới access token",
    description="Xoay vòng refresh token trong cookie HttpOnly và trả access token mới. "
                "Một yêu cầu đồng thời dùng token vừa bị thay vẫn được chấp nhận trong cửa sổ ân hạn.",
    dependencies=[Depends(same_origin)],
)
@transaction
async def refresh(refresh_token: RefreshTokenCookie, auth_service: AuthServiceDep):
    return await auth_service.refresh(refresh_token)


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
