from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class PendingAction(BaseModel):
    action_id: str
    revision: int
    tool: str
    preview: str
    payload: dict[str, Any]
    payload_hash: str
    expires_at: datetime

class ChatResponse(BaseModel):
    session_id: str
    run_id: str
    reply: str
    status: Literal['completed', 'needs_input', 'pending_confirmation', 'failed']
    intent: str | None = None
    agent_used: str = 'orchestration_agent'
    pending_action: PendingAction | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
