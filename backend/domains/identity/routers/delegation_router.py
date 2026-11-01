"""Danh tính uỷ quyền cho service agent (POST /api/v2/auth/delegations).

Agent trình access token của người dùng *và* chứng minh mình là service agent
(core/service_auth.py). Backend trả về token uỷ quyền ngắn hạn:
lệnh đọc bằng token này được nhận diện là của trợ lý, nên consent áp dụng trên mọi
đường đi, bất kể bên gọi đặt header gì.
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.dependencies import UserContextDep
from core import principal as principals
from core import service_auth
from core.security import create_delegated_token
from core.settings import settings
from domains.identity import consent

router = APIRouter(prefix="/auth", tags=["auth"])


class DelegationRead(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    consent_version: int
    device_data_allowed: bool


@router.post("/delegations", response_model=DelegationRead, summary="Cấp token uỷ quyền ngắn hạn cho trợ lý",
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
