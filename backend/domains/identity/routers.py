"""Router HTTP của miền danh tính và quyền riêng tư."""

from datetime import date, datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import UserContextDep, UserDataServiceDep
from core import principal as principals
from core import service_auth
from core.idempotency import IdempotentRoute
from core.rate_limit import SlidingWindowLimiter, client_key, enforce
from core.security import (
    PKCE_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_NAME,
    STATE_COOKIE_NAME,
    BearerCredentials,
    RefreshTokenCookie,
    create_delegated_token,
    decode_access_token,
    require_user_principal,
)
from core.settings import settings
from core.transaction import transaction
from domains.identity import consent
from domains.identity.schemas import LogoutResponse, OnboardingInput, UserRead, UserUpdate
from domains.identity.services import (
    AuthService,
    AuthServiceDep,
    erase_user,
    export_user_data,
    purge_agent_conversations,
)
from domains.shared.schemas import JsonObjectInput

# --------------------------------------------------------------------------------------------------
# Router xác thực: Google OAuth (PKCE), xoay refresh token và đăng xuất.
# --------------------------------------------------------------------------------------------------

_limiter = SlidingWindowLimiter(settings.AUTH_RATE_LIMIT_PER_MINUTE)


def limit_auth(request: Request) -> None:
    enforce(_limiter, client_key(request))


def same_origin(request: Request) -> None:
    """POST xác thực bằng cookie phải đến từ origin trình duyệt được phép (CSRF); thiếu header Origin cũng bị từ chối."""
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in {o.rstrip("/") for o in [*settings.CORS_ORIGINS, settings.FRONTEND_URL]}:
        raise HTTPException(403, "Origin is not allowed")


auth_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(limit_auth)])


@auth_router.get(
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


@auth_router.post(
    "/refresh",
    summary="Làm mới access token",
    description="Xoay vòng refresh token trong cookie HttpOnly và trả access token mới. "
                "Một yêu cầu đồng thời dùng token vừa bị thay vẫn được chấp nhận trong cửa sổ ân hạn.",
    dependencies=[Depends(same_origin)],
)
@transaction
async def refresh(refresh_token: RefreshTokenCookie, auth_service: AuthServiceDep):
    return await auth_service.refresh(refresh_token)


@auth_router.post(
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


# --------------------------------------------------------------------------------------------------
# Danh tính uỷ quyền cho service agent (POST /api/v2/auth/delegations).
#
# Agent trình access token của người dùng *và* chứng minh mình là service agent
# (core/service_auth.py). Backend trả về token uỷ quyền ngắn hạn:
# lệnh đọc bằng token này được nhận diện là của trợ lý, nên consent áp dụng trên mọi
# đường đi, bất kể bên gọi đặt header gì.
# --------------------------------------------------------------------------------------------------

delegation_router = APIRouter(prefix="/auth", tags=["auth"])


class DelegationRead(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    consent_version: int
    device_data_allowed: bool


@delegation_router.post("/delegations", response_model=DelegationRead, summary="Cấp token uỷ quyền ngắn hạn cho trợ lý",
             description="Chỉ dịch vụ trợ lý (chứng minh bằng chữ ký X-HercFit-Service) đổi token người dùng lấy "
                         "token uỷ quyền. Mọi lượt đọc bằng token này được xem là của trợ lý và tuân theo đồng ý.")
async def create_delegation(request: Request, service: UserContextDep):
    current = principals.current()
    if current is None or current.delegated:
        raise HTTPException(403, "A delegated token cannot create another delegation")
    body = await request.body()
    if not service_auth.verify(settings.agent_service_secrets, request.headers.get(service_auth.HEADER),
                               request.method, request.url.path, str(service.user_id), body):
        raise HTTPException(403, "Service proof required")
    decision = await consent.load(service.session, service.user_id)
    token, expires = create_delegated_token(service.user_id, consent_version=decision.version)
    return DelegationRead(access_token=token, expires_at=expires, consent_version=decision.version,
                          device_data_allowed=decision.device)


# --------------------------------------------------------------------------------------------------
# Export and erasure of the authenticated user's data (Luật Bảo vệ dữ liệu cá nhân 2025).
# --------------------------------------------------------------------------------------------------

privacy_router = APIRouter(prefix="/profile", tags=["privacy"], dependencies=[Depends(require_user_principal)])


class EraseRequest(BaseModel):
    confirm_email: str = Field(min_length=3, max_length=255, description="Nhập đúng email tài khoản để xác nhận xoá vĩnh viễn")


@privacy_router.get("/export", summary="Xuất toàn bộ dữ liệu cá nhân (JSON)")
async def export_data(service: UserContextDep):
    data = await export_user_data(service.session, service.user_id)
    filename = f"hercfit-export-{date.today().isoformat()}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@privacy_router.post("/erase", summary="Xoá vĩnh viễn tài khoản và dữ liệu",
             description="Xoá thật (không phải vô hiệu hoá), gồm cả hội thoại với trợ lý. Service agent không xoá được "
                         "hội thoại thì trả 503 và không xoá gì.")
@transaction
async def erase_account(payload: EraseRequest, service: UserContextDep):
    if payload.confirm_email.strip().lower() != str(service.user.email).lower():
        raise HTTPException(422, "Email xác nhận không khớp với tài khoản")
    # Hội thoại ở service agent bị xoá trước; agent lỗi thì dừng ở đây (503), backend chưa xoá gì.
    await purge_agent_conversations(service.user_id)
    receipt = await erase_user(service.session, service.user_id)
    response = JSONResponse(receipt)
    for cookie in (REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME, PKCE_COOKIE_NAME):
        response.delete_cookie(cookie, path="/")
    return response


# --------------------------------------------------------------------------------------------------
# Hồ sơ của người dùng đã xác thực; danh tính được tạo bởi OAuth.
# --------------------------------------------------------------------------------------------------

profile_router = APIRouter(route_class=IdempotentRoute, prefix="/profile", tags=["profile"])


@profile_router.get("", response_model=UserRead)
async def get_profile(service: UserDataServiceDep):
    return service.user


@profile_router.patch("", response_model=UserRead)
@transaction
async def update_profile(payload: UserUpdate, service: UserDataServiceDep):
    return await service.update_profile(payload)


@profile_router.patch("/personal-info", response_model=UserRead)
@transaction
async def merge_personal_info(payload: JsonObjectInput, service: UserDataServiceDep):
    """Gộp các nhóm cấp cao nhất; thay toàn bộ giá trị của từng nhóm được truyền."""
    return await service.merge_personal_info(payload.root)


@profile_router.post("/onboarding", response_model=UserRead)
@transaction
async def complete_onboarding(payload: OnboardingInput, service: UserDataServiceDep):
    """Lưu nguyên tử hồ sơ, số đo ban đầu (tuỳ chọn) và mục tiêu đã xác nhận."""
    return await service.onboard(payload)


@profile_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
@transaction
async def delete_profile(service: UserDataServiceDep) -> Response:
    """Vô hiệu hoá tài khoản và thu hồi mọi phiên refresh; giữ lại lịch sử."""
    await service.delete_profile()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    for cookie in (REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME):
        response.delete_cookie(cookie, path="/")
    return response
