"""/api/v2: API của nền tảng sức khoẻ (phân trang bằng cursor, 202 + operation id cho lệnh bất đồng bộ).

/api (v1) giữ nguyên qua các adapter trong khi các bên dùng chuyển dần (docs/google_health/).
"""
from fastapi import APIRouter

from domains.analytics.routers.context_router import router as context_router
from domains.health_records.routers.health_v2_router import router as health_router
from domains.identity.routers.delegation_router import router as delegation_router
from domains.shared.routers.operations_router import router as operations_router
from integrations.google_health.router_v2 import router as google_health_router
from integrations.google_health.webhook import router as google_health_webhook_router

api_v2_router = APIRouter()
api_v2_router.include_router(delegation_router)
api_v2_router.include_router(operations_router)
api_v2_router.include_router(health_router)
api_v2_router.include_router(context_router)
api_v2_router.include_router(google_health_router)
# Công khai: Google xác thực bằng secret của subscriber và chữ ký, không phải token người dùng.
api_v2_router.include_router(google_health_webhook_router)

__all__ = ["api_v2_router"]
