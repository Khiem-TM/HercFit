"""Export and erasure of the authenticated user's data (Luật Bảo vệ dữ liệu cá nhân 2025)."""
from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.security import PKCE_COOKIE_NAME, REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME
from core.transaction import transaction
from routers.dependencies import UserContextDep
from services.privacy_service import erase_user, export_user_data

router = APIRouter(prefix="/profile", tags=["privacy"])


class EraseRequest(BaseModel):
    confirm_email: str = Field(min_length=3, max_length=255, description="Nhập đúng email tài khoản để xác nhận xoá vĩnh viễn")


@router.get("/export", summary="Xuất toàn bộ dữ liệu cá nhân (JSON)")
async def export_data(service: UserContextDep):
    data = await export_user_data(service.session, service.user_id)
    filename = f"hercfit-export-{date.today().isoformat()}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/erase", summary="Xoá vĩnh viễn tài khoản và dữ liệu",
             description="Xoá thật (không phải vô hiệu hoá). Hội thoại với trợ lý cần xoá riêng qua DELETE /api/v1/chat/me.")
@transaction
async def erase_account(payload: EraseRequest, service: UserContextDep):
    if payload.confirm_email.strip().lower() != str(service.user.email).lower():
        raise HTTPException(422, "Email xác nhận không khớp với tài khoản")
    receipt = await erase_user(service.session, service.user_id)
    response = JSONResponse(receipt)
    for cookie in (REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME, PKCE_COOKIE_NAME):
        response.delete_cookie(cookie, path="/")
    return response
