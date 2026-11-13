"""DELETE /internal/users/{user_id}/conversations: backend xoá mọi cuộc trò chuyện của một người dùng trước khi xoá
tài khoản (privacy_router.erase_account).

Chỉ backend gọi được: chữ ký HMAC (core/service_auth) trên method, đường dẫn, người dùng và thân request, bằng
AGENT_SERVICE_SECRET dùng chung, như notify_router; người dùng được ký là người dùng trên đường dẫn. Không có khoá
thì endpoint đóng (503); sai chữ ký thì 401.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from core import service_auth

router = APIRouter(prefix="/internal/users", include_in_schema=False)


@router.delete("/{user_id}/conversations")
async def purge_conversations(user_id: UUID, request: Request):
    settings = request.app.state.settings
    secret = settings.AGENT_SERVICE_SECRET.get_secret_value() if getattr(settings, "AGENT_SERVICE_SECRET", None) else ""
    if not secret:
        raise HTTPException(503, "Conversation purge is not configured")
    if not service_auth.verify([secret], request.headers.get(service_auth.HEADER), "DELETE", request.url.path,
                               str(user_id), await request.body()):
        raise HTTPException(401, "Invalid service signature")
    return await request.app.state.runtime.purge_user(str(user_id))
