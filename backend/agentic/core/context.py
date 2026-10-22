from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

@dataclass
class RequestContext:
    user_id: str
    token: str
    backend: Any
    private_values: tuple[str, ...] = ()

# Never place credentials in graph state, messages, or configurable/checkpoints.
request_context: ContextVar[RequestContext] = ContextVar('agent_request_context')
