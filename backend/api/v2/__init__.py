"""/api/v2: the health platform API (cursor pagination, 202 + operation id for async commands).

/api (v1) stays unchanged through adapters while consumers move (docs/google_health/).
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
# Public: Google authenticates with the subscriber secret and a signature, not a user token.
api_v2_router.include_router(google_health_webhook_router)

__all__ = ["api_v2_router"]
