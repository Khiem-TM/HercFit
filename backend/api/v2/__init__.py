"""/api/v2: delegation cho trợ lý, ngữ cảnh sức khoẻ có nguồn, dữ liệu sức khoẻ, ghi xuyên qua Google và thông báo."""
from fastapi import APIRouter

from domains.analytics.routers.context_router import router as context_router
from domains.health_records.routers.health_v2_router import router as health_router
from domains.identity.routers.delegation_router import router as delegation_router
from domains.notifications.routers.notifications_router import router as notifications_router
from integrations.google_health.router import records_router as google_health_records_router

api_v2_router = APIRouter()
api_v2_router.include_router(delegation_router)
api_v2_router.include_router(health_router)
api_v2_router.include_router(google_health_records_router)
api_v2_router.include_router(context_router)
api_v2_router.include_router(notifications_router)

__all__ = ["api_v2_router"]
