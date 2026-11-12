"""Google Health: kết nối (đồng ý OAuth, trạng thái, consent, đồng bộ, ngắt kết nối) và ghi xuyên qua.

* /api/integrations/google-health ...: kết nối của người dùng.
* /api/v2/health/records/{kind}: buổi thể thao, cân nặng, chiều cao, % mỡ, nước uống được ghi thẳng
  lên Google (Google là nguồn sự thật) rồi lưu ngay bản sao vào health_points.
"""
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Cookie, Query, Response, status
from fastapi.responses import RedirectResponse

from api.dependencies import SessionDep, UserContextDep, service_dependency
from core.idempotency import IdempotentRoute
from core.rate_limit import SlidingWindowLimiter, enforce
from core.settings import settings
from core.transaction import transaction
from integrations.google_health import oauth, records
from integrations.google_health.connection import (
    HealthConnectionService,
    complete_connect,
    frontend_result,
)
from integrations.google_health.schemas import (
    HealthConnectionRead,
    HealthConnectRequest,
    HealthConnectResponse,
    HealthConsentUpdate,
    HealthRecordRead,
    HealthSyncAccepted,
    HealthSyncSettingsUpdate,
)
from integrations.google_health.sync import BACKFILL_DAYS, run

router = APIRouter(prefix="/integrations/google-health", tags=["integrations"])
records_router = APIRouter(prefix="/health/records", tags=["health-data"], route_class=IdempotentRoute)
HealthConnectionServiceDep = Annotated[HealthConnectionService, service_dependency(HealthConnectionService)]
COOKIE_PATH = "/api/integrations/google-health"
# Theo người dùng: bắt đầu đồng ý và đồng bộ thủ công đều gọi Google, nên các đợt dồn dập bị từ chối.
_limiter = SlidingWindowLimiter(6)


def _set_cookie(response: Response, key: str, value: str) -> None:
    response.set_cookie(key=key, value=value, httponly=True, secure=settings.cookie_secure, samesite="lax",
                        max_age=oauth.STATE_SECONDS, path=COOKIE_PATH)


@router.get("", response_model=HealthConnectionRead, summary="Trạng thái kết nối Google Health")
async def get_connection(service: HealthConnectionServiceDep):
    return await service.status()


@router.post("/connect", response_model=HealthConnectResponse, summary="Bắt đầu kết nối Google Health",
             description="Trả URL đồng ý của Google (offline; đọc dữ liệu sức khoẻ và ghi những gì HercFit ghi). "
                         "Callback chỉ chấp nhận đúng tài khoản Google đang dùng để đăng nhập HercFit.")
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
        from integrations.google_health.models import HealthConnection

        connection = await session.get(HealthConnection, connection_id)
        background.add_task(run, connection.user_id, days=BACKFILL_DAYS)
    response = RedirectResponse(frontend_result(result), status_code=status.HTTP_302_FOUND)
    for cookie in (oauth.NONCE_COOKIE, oauth.PKCE_COOKIE):
        response.delete_cookie(cookie, path=COOKIE_PATH)
    return response


@router.patch("", response_model=HealthConnectionRead, summary="Bật/tắt cho phép trợ lý dùng dữ liệu sức khoẻ")
@transaction
async def update_consent(payload: HealthConsentUpdate, service: HealthConnectionServiceDep):
    return await service.update_consent(payload.share_with_assistant, sensitive=payload.share_sensitive_with_assistant)


@router.patch("/settings", response_model=HealthConnectionRead, summary="Nhóm dữ liệu đồng bộ và tần suất đồng bộ",
              description="groups: sleep, rhr, hrv, steps, body (false = dừng đọc nhóm đó, dữ liệu cũ giữ nguyên). "
                          "frequency: hourly (nền mỗi giờ), open (khi mở ứng dụng), manual (chỉ khi bấm đồng bộ).")
@transaction
async def update_settings(payload: HealthSyncSettingsUpdate, service: HealthConnectionServiceDep):
    from core import principal
    if principal.is_agent():
        from fastapi import HTTPException
        raise HTTPException(403, "Chỉ người dùng được đổi cài đặt đồng bộ.")
    return await service.update_settings(payload.groups, payload.frequency)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, response_model=HealthSyncAccepted,
             summary="Đồng bộ ngay", description="Đọc lại 7 ngày gần nhất bằng reconcile rồi đẩy gym và bữa ăn. "
                                                 "Theo dõi kết quả qua GET (last_sync_at, types).")
async def sync_now(service: HealthConnectionServiceDep, background: BackgroundTasks):
    enforce(_limiter, f"sync:{service.user_id}")
    await service.require_active()
    background.add_task(run, service.user_id)
    return HealthSyncAccepted(detail="Đang đồng bộ dữ liệu Google Health.")


@router.delete("", response_model=HealthConnectionRead, summary="Ngắt kết nối Google Health",
               description="Thu hồi quyền tại Google và xoá token. purge_data=true xoá luôn bản sao dữ liệu trong HercFit.")
@transaction
async def disconnect(service: HealthConnectionServiceDep, purge_data: bool = False):
    return await service.disconnect(purge_data)


# ------------------------------------------------------------------------------ ghi xuyên qua
@records_router.post("/{kind}:preview", summary="Xem trước data point sẽ ghi lên Google (không gọi Google)")
async def preview_record(kind: records.Kind, payload: dict[str, Any], service: UserContextDep):
    return await records.preview(service.session, service.user_id, kind, payload)


@records_router.post("/{kind}", status_code=status.HTTP_201_CREATED, response_model=HealthRecordRead,
                     summary="Ghi lên Google Health",
                     description="exercise (buổi thể thao: exercise_id + performance như một mục buổi tập), weight (kg), "
                                 "height (cm), body-fat (%), hydration (ml).")
@transaction
async def create_record(kind: records.Kind, payload: dict[str, Any], service: UserContextDep):
    return await records.create(service.session, service.user_id, kind, payload)


@records_router.patch("/{kind}/{record_id}", response_model=HealthRecordRead,
                      summary="Sửa một bản ghi HercFit đã ghi lên Google")
@transaction
async def update_record(kind: records.Kind, record_id: UUID, payload: dict[str, Any], service: UserContextDep):
    return await records.update(service.session, service.user_id, kind, record_id, payload)


@records_router.delete("/{kind}/{record_id}", status_code=status.HTTP_204_NO_CONTENT,
                       summary="Xoá một bản ghi HercFit đã ghi lên Google")
@transaction
async def delete_record(kind: records.Kind, record_id: UUID, service: UserContextDep):
    await records.delete(service.session, service.user_id, kind, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
