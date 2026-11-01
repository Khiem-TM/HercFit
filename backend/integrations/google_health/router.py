"""Google Health connection: OAuth consent, status, assistant consent, sync and disconnect."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Query, Response, status
from fastapi.responses import RedirectResponse

from core.rate_limit import SlidingWindowLimiter, enforce
from core.settings import settings
from core.transaction import transaction
from api.dependencies import SessionDep, service_dependency
from integrations.google_health.schemas import (
    HealthConnectRequest,
    HealthConnectResponse,
    HealthConnectionRead,
    HealthConsentUpdate,
    HealthSyncAccepted,
)
from integrations.google_health import oauth
from integrations.google_health.connection import HealthConnectionService, complete_connect, frontend_result
from integrations.google_health.sync import sync_connection

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
    if connection_id is not None and settings.GH_WORKER_EXTERNAL:
        # The worker owns every Google call: the callback only records the work, in this transaction.
        await _enqueue_initial(session, connection_id)
    await session.commit()
    if connection_id is not None and not settings.GH_WORKER_EXTERNAL:
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
    if settings.GH_WORKER_EXTERNAL:
        from core.jobs import queue
        from integrations.google_health.models import HealthConnection

        connection = await service.session.get(HealthConnection, connection_id)
        kind = "GH_LEGACY_SYNC" if settings.GH_INGEST_V2 == "off" else "GH_RECONCILE"
        await queue.enqueue(service.session, kind, user_id=service.user_id, connection_id=connection_id,
                            connection_generation=connection.generation, priority=90,
                            dedupe_key=f"manual:{connection_id}", payload={"reason": "manual"})
        await service.session.commit()
    else:
        background.add_task(sync_connection, connection_id, trigger="MANUAL")
    return HealthSyncAccepted(detail="Đang đồng bộ dữ liệu Google Health.")


async def _enqueue_initial(session, connection_id) -> None:
    from core.jobs import queue
    from integrations.google_health.models import HealthConnection

    connection = await session.get(HealthConnection, connection_id)
    base = {"user_id": connection.user_id, "connection_id": connection.id,
            "connection_generation": connection.generation}
    if settings.GH_INGEST_V2 == "off":
        await queue.enqueue(session, "GH_LEGACY_SYNC", priority=95, dedupe_key=f"initial:{connection.id}", **base)
        return
    await queue.enqueue(session, "GH_IDENTITY_REFRESH", priority=95,
                        dedupe_key=f"identity:{connection.id}:{connection.generation}", **base)
    await queue.enqueue(session, "GH_ONBOARD", priority=90,
                        dedupe_key=f"onboard:{connection.id}:{connection.generation}", **base)


@router.delete("", response_model=HealthConnectionRead, summary="Ngắt kết nối Google Health",
               description="Thu hồi quyền tại Google và xoá token. purge_data=true xoá luôn dữ liệu đã đồng bộ.")
@transaction
async def disconnect(service: HealthConnectionServiceDep, purge_data: bool = False):
    return await service.disconnect(purge_data)
