"""Read-only context for the HercFit assistant (one round trip per conversation turn)."""
from fastapi import APIRouter, Request

from routers.dependencies import UserContextDep
from schemas.assistant import AssistantContextRead
from schemas.tracking import TimeZoneName
from services import assistant_context
from services.health_service import AGENT_CLIENT_HEADER

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/context", response_model=AssistantContextRead)
async def get_assistant_context(request: Request, service: UserContextDep, timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    agent = request.headers.get(AGENT_CLIENT_HEADER, "").lower() == "agent"
    return await assistant_context.build(service.session, service.user, timezone=timezone, agent=agent)
