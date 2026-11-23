"""Router HTTP của miền thông báo."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, WebSocket, status

from api.dependencies import UserContextDep
from core import principal
from core.idempotency import IdempotentRoute
from core.rate_limit import SlidingWindowLimiter, enforce
from core.transaction import transaction
from domains.notifications import services
from domains.notifications.schemas import (
    NotificationList,
    NotificationPreferences,
    NotificationPreferencesRead,
    NotificationRead,
)

# --------------------------------------------------------------------------------------------------
# /api/v2/notifications: hộp thư trong ứng dụng và tuỳ chọn thông báo chủ động.
#
# Chỉ người dùng (không phải trợ lý) đọc và đổi được: thông báo chứa tóm tắt dữ liệu thiết bị, còn bật
# thông báo chủ động là một consent.
# --------------------------------------------------------------------------------------------------

notifications_router = APIRouter(prefix="/notifications", tags=["notifications"], route_class=IdempotentRoute)
_review_limiter = SlidingWindowLimiter(6)


def _user_only() -> None:
    if principal.is_agent():
        raise HTTPException(403, "Chỉ người dùng xem và đổi được thông báo của mình.")


@notifications_router.get("", response_model=NotificationList, summary="Hộp thư thông báo (mới nhất trước)")
async def list_notifications(service: UserContextDep, status_filter: Annotated[
        Literal["unread", "all"], Query(alias="status")] = "all",
        limit: Annotated[int, Query(ge=1, le=50)] = 20):
    _user_only()
    return await services.inbox(service.session, service.user_id, unread_only=status_filter == "unread", limit=limit)


@notifications_router.get("/preferences", response_model=NotificationPreferencesRead, summary="Tuỳ chọn thông báo chủ động")
async def get_preferences(service: UserContextDep):
    _user_only()
    return await services.preferences(service.session, service.user)


@notifications_router.put("/preferences", response_model=NotificationPreferencesRead, summary="Bật/tắt và chỉnh thông báo chủ động",
            description="enabled là consent 'proactive' (có lịch sử trong consent_events); mặc định tắt.")
@transaction
async def put_preferences(update: NotificationPreferences, service: UserContextDep):
    _user_only()
    return await services.save_preferences(service.session, service.user, update)


@notifications_router.post("/review:run", response_model=NotificationList, summary="Tạo đánh giá ngày hôm nay ngay",
             description="Không chờ giờ đánh giá hay giờ yên lặng; vẫn một lần mỗi ngày và cần đã bật thông báo chủ động.")
@transaction
async def run_review(service: UserContextDep):
    _user_only()
    enforce(_review_limiter, f"review:{service.user_id}")
    await services.evaluate(service.session, service.user, force=True)
    return await services.inbox(service.session, service.user_id)


@notifications_router.websocket("/stream")
async def notification_stream(websocket: WebSocket):
    """Thông báo tức thì. Tin nhắn đầu tiên phải là {"type": "auth", "token": "<access token>"} (xem realtime)."""
    await services.stream(websocket)


@notifications_router.post("/{notification_id}:seen", response_model=NotificationRead, summary="Đánh dấu đã xem")
@transaction
async def mark_seen(notification_id: UUID, service: UserContextDep):
    _user_only()
    return await services.mark_seen(service.session, service.user_id, notification_id)


@notifications_router.post("/{notification_id}:dismiss", status_code=status.HTTP_204_NO_CONTENT, summary="Bỏ qua thông báo")
@transaction
async def dismiss(notification_id: UUID, service: UserContextDep):
    _user_only()
    await services.dismiss(service.session, service.user_id, notification_id)
