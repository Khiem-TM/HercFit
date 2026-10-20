"""API Request DTOs for external clients interacting with the HercFit Agentic Service."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Input payload for invoking or streaming the Multi-Agent chat endpoint."""

    message: str = Field(
        min_length=1,
        max_length=8000,
        description="User message or query sent to the Agent system.",
        examples=["Tính giúp tôi BMI và TDEE cho nam 72kg, cao 175cm, 26 tuổi"],
    )
    session_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Conversation session/thread ID used to persist context.",
    )
    user_id: str | None = Field(
        default=None,
        description="Optional user ID for cross-session personalization.",
    )
    model: str | None = Field(
        default=None,
        description="Optional LLM model override.",
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream response chunks via Server-Sent Events.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary client context metadata.",
    )


class MemoryStoreRequest(BaseModel):
    """Request DTO to explicitly store a long-term user fact."""

    user_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)

