"""Timeout của client model theo chế độ trò chuyện (agentic/core/llm.py, services/mode.py).

Router (vai trò decision) ở chế độ Plan cần ngân sách dài hơn ROUTING_TIMEOUT_SECONDS: lượt Plan từng thất bại vì ba
lần gọi router liên tiếp vượt 12 s. Chế độ thường giữ nguyên 12 s. Dựng client không gọi mạng.
"""
import pytest
from pydantic import SecretStr

from agentic.core.llm import Models
from agentic.services import mode
from evaluation.adapters.graph_runtime import eval_settings


def timeout_of(chat_mode, role):
    marker = mode.current.set(chat_mode)
    try:
        client = Models(eval_settings(FPT_API_KEY=SecretStr("test-only"))).get(role)
    finally:
        mode.current.reset(marker)
    return client.request_timeout


@pytest.mark.parametrize(("chat_mode", "role", "expected"), [
    (mode.PLAN, "decision", 30),
    (mode.NORMAL, "decision", 12),
    (mode.PLAN, "research", 60),
    (mode.PLAN, "response", 90),
])
def test_role_timeouts_by_mode(chat_mode, role, expected):
    assert timeout_of(chat_mode, role) == expected
