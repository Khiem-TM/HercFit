from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GraphContext(BaseModel):
    facts: list[dict[str, Any]] = Field(default_factory=list)
    # Các lượt hội thoại gần đây (lọc theo thế hệ phiên đang sống).
    episodes: list[dict[str, Any]] = Field(default_factory=list)
    # Model người dùng suy ra (knowledge_graph.model) và các mục liên quan đến yêu cầu.
    model: dict[str, Any] | None = None
    sections: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    intents: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    projection_lag_ms: float | None = None
    status: Literal['ok', 'empty', 'timeout', 'unavailable', 'blocked', 'warming'] = 'empty'


class ProjectionEvent(BaseModel):
    event_id: UUID
    source: Literal['backend', 'agent']
    aggregate_type: Literal['User', 'Goal', 'BodyMetric', 'Meal', 'Food', 'Training', 'Execution', 'Session', 'Run',
                            'DailyHealth', 'SleepSession', 'DeviceWorkout']
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
