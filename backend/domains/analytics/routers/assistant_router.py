"""Ngữ cảnh chỉ đọc cho trợ lý HercFit (mỗi lượt hội thoại một lượt gọi)."""
from fastapi import APIRouter

from api.dependencies import UserContextDep
from domains.analytics.schemas.assistant import AssistantContextRead
from domains.shared.schemas.tracking import TimeZoneName
from domains.analytics.services import assistant_context

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/context", response_model=AssistantContextRead)
async def get_assistant_context(service: UserContextDep, timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    # Ai đọc (người dùng hay trợ lý) lấy từ principal đã xác thực, không phải header.
    return await assistant_context.build(service.session, service.user, timezone=timezone)
