"""Assistant context snapshot: what HercFit already knows about the user."""
from typing import Any

from pydantic import BaseModel


class AssistantContextRead(BaseModel):
    generated_at: str
    timezone: str
    today: str
    profile: dict[str, Any]
    body: dict[str, Any]
    goal: dict[str, Any] | None
    athlete: dict[str, Any]
    running: dict[str, Any]
    training_4w: dict[str, Any]
    inventory: dict[str, Any]
    # Coaching facts with no stored value; the only ones the assistant may ask the user for.
    missing: list[str]
