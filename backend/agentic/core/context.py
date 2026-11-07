from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class RequestContext:
    user_id: str
    token: str
    backend: Any
    private_values: tuple[str, ...] = ()


# Không bao giờ đặt thông tin xác thực vào graph state, tin nhắn hay configurable/checkpoint.
request_context: ContextVar[RequestContext] = ContextVar("agent_request_context")
