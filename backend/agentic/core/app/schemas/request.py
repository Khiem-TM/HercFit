from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    # Accepted for backwards compatibility, never used as identity.
    user_id: str | None = None

class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=128)
    action_id: str
    revision: int = Field(ge=1)
    decision: Literal['approve', 'reject']
