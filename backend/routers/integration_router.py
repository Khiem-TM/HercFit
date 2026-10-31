"""Google Health connection: OAuth consent, status, assistant consent, sync and disconnect."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Query, Response, status
from fastapi.responses import RedirectResponse

from core.rate_limit import SlidingWindowLimiter, enforce
from core.settings import settings
from core.transaction import transaction
from routers.dependencies import SessionDep, service_dependency
from schemas.health import (
    HealthConnectRequest, HealthConnectResponse, HealthConnectionRead, HealthConsentUpdate, HealthSyncAccepted,
)
from services.google_health import oauth
from services.google_health.connection import HealthConnectionService, complete_connect, frontend_result
from services.google_health.sync import sync_connection

router = APIRouter(prefix="/integrations/google-health", tags=["integrations"])
HealthConnectionServiceDep = Annotated[HealthConnectionService, service_dependency(HealthConnectionService)]
COOKIE_PATH = "/api/integrations/google-health"
# Per user: starting consent and manual syncs call Google, so bursts are refused.
_limiter = SlidingWindowLimiter(6)


def _set_cookie(response: Response, key: str, value: str) -> None:
    response.set_cookie(key=key, value=value, httponly=True, secure=settings.cookie_secure, samesite="lax",
                        max_age=oauth.STATE_SECONDS, path=COOKIE_PATH)


@router.get("", response_model=HealthConnectionRead, summary="Trạng thái kết nối Google Health")
async def get_connection(service: HealthConnectionServiceDep):
    return await service.status()


@router.post("/connect", response_model=HealthConnectResponse, summary="Bắt đầu kết nối Google Health",
             description="Trả URL đồng ý của Google (offline, chỉ đọc). Callback chỉ chấp nhận đúng tài khoản Google "
                         "đang dùng để đăng nhập HercFit.")
async def connect(payload: HealthConnectRequest, service: HealthConnectionServiceDep, response: Response):
    enforce(_limiter, f"connect:{service.user_id}")
    url, nonce, verifier = service.start(payload.share_with_assistant)
    _set_cookie(response, oauth.NONCE_COOKIE, nonce)
    _set_cookie(response, oauth.PKCE_COOKIE, verifier)
    return HealthConnectResponse(authorization_url=url)


@router.get("/callback", include_in_schema=False)
async def callback(
    session: SessionDep, background: BackgroundTasks,
    code: str | None = Query(default=None), state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    nonce: str | None = Cookie(default=None, alias=oauth.NONCE_COOKIE),
    verifier: str | None = Cookie(default=None, alias=oauth.PKCE_COOKIE),
):
    result, connection_id = await complete_connect(session, code=code, state=state, error=error,
                                                   nonce_cookie=nonce, verifier=verifier)
    await session.commit()
    if connection_id is not None:
        background.add_task(sync_connection, connection_id, trigger="INITIAL")
    response = RedirectResponse(frontend_result(result), status_code=status.HTTP_302_FOUND)
    for cookie in (oauth.NONCE_COOKIE, oauth.PKCE_COOKIE):
        response.delete_cookie(cookie, path=COOKIE_PATH)
    return response


@router.patch("", response_model=HealthConnectionRead, summary="Bật/tắt cho phép trợ lý dùng dữ liệu sức khoẻ")
@transaction
async def update_consent(payload: HealthConsentUpdate, service: HealthConnectionServiceDep):
    return await service.update_consent(payload.share_with_assistant)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=HealthSyncAccepted,
             summary="Đồng bộ ngay")
async def sync_now(service: HealthConnectionServiceDep, background: BackgroundTasks):
    enforce(_limiter, f"sync:{service.user_id}")
    connection_id = await service.request_sync()
    background.add_task(sync_connection, connection_id, trigger="MANUAL")
    return HealthSyncAccepted(detail="Đang đồng bộ dữ liệu Google Health.")


@router.delete("", response_model=HealthConnectionRead, summary="Ngắt kết nối Google Health",
               description="Thu hồi quyền tại Google và xoá token. purge_data=true xoá luôn dữ liệu đã đồng bộ.")
@transaction
async def disconnect(service: HealthConnectionServiceDep, purge_data: bool = False):
    return await service.disconnect(purge_data)
