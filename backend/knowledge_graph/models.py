from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GraphContext(BaseModel):
    facts: list[dict[str, Any]] = Field(default_factory=list)
    # Recent conversation turns (gated by live session generations).
    episodes: list[dict[str, Any]] = Field(default_factory=list)
    # Derived user model (knowledge_graph.model) and the sections relevant to the request.
    model: dict[str, Any] | None = None
    sections: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    intents: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    projection_lag_ms: float | None = None
    status: Literal['off', 'ok', 'empty', 'timeout', 'unavailable', 'blocked', 'warming'] = 'empty'


class ProjectionEvent(BaseModel):
    event_id: UUID
    source: Literal['backend', 'agent']
    aggregate_type: Literal['User', 'Goal', 'BodyMetric', 'Meal', 'Food', 'Training', 'Execution', 'Session', 'Run']
    aggregate_id: str
    owner_id: str | None = None
    aggregate_version: int = Field(ge=1)
    operation: Literal['upsert', 'delete']
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1

    @property
    def key(self) -> str:
        return f'{self.source}:{self.aggregate_type}:{self.aggregate_id}'
