"""Read-only context for the HercFit assistant (one round trip per conversation turn)."""
from fastapi import APIRouter

from api.dependencies import UserContextDep
from domains.analytics.schemas.assistant import AssistantContextRead
from domains.shared.schemas.tracking import TimeZoneName
from domains.analytics.services import assistant_context

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/context", response_model=AssistantContextRead)
async def get_assistant_context(service: UserContextDep, timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    # Who reads (user or assistant) comes from the authenticated principal, not a header.
    return await assistant_context.build(service.session, service.user, timezone=timezone)
