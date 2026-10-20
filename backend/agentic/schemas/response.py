"""API Response DTOs returned by the HercFit Agentic Service."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ChatResponse(BaseModel):
    """Unified response returned after executing the Multi-Agent workflow."""

    session_id: str
    run_id: str
    reply: str
    intent: str | None = None
    agent_used: str | None = None
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatHistoryMessageDTO(BaseModel):
    role: str
    content: str
    name: str | None = None


class ChatHistoryResponse(BaseModel):
    session_id: str
    message_count: int
    messages: list[ChatHistoryMessageDTO] = Field(default_factory=list)


class AgentHealthResponse(BaseModel):
    status: str = "ok"
    service: str = "hercfit-agentic"
    default_model: str
    fake_model_enabled: bool
    checkpoint_backend: str

