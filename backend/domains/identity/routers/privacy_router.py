"""Export and erasure of the authenticated user's data (Luật Bảo vệ dữ liệu cá nhân 2025)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.dependencies import UserContextDep
from core.security import (
    PKCE_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_NAME,
    STATE_COOKIE_NAME,
    require_user_principal,
)
from core.transaction import transaction
from domains.identity.services.privacy_service import (
    erase_user,
    export_user_data,
    purge_agent_conversations,
)

router = APIRouter(prefix="/profile", tags=["privacy"], dependencies=[Depends(require_user_principal)])


class EraseRequest(BaseModel):
    confirm_email: str = Field(min_length=3, max_length=255, description="Nhập đúng email tài khoản để xác nhận xoá vĩnh viễn")


@router.get("/export", summary="Xuất toàn bộ dữ liệu cá nhân (JSON)")
async def export_data(service: UserContextDep):
    data = await export_user_data(service.session, service.user_id)
    filename = f"hercfit-export-{date.today().isoformat()}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/erase", summary="Xoá vĩnh viễn tài khoản và dữ liệu",
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
