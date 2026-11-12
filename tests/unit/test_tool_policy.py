"""Chính sách tool của agent (agentic/tools/policy.py, ToolAgent.execute_calls): allowlist theo miền, tuyến chỉ đọc,
giới hạn số lời gọi. Backend giả của bộ eval, không gọi mạng."""
import pytest

from agentic.agents.tool_agent import ToolAgent
from agentic.core.context import RequestContext, request_context
from agentic.tools.policy import allowed_tools
from evaluation.adapters.fixtures import EvalBackend, EvalStore, token_for
from evaluation.adapters.graph_runtime import eval_settings

USER = "u-policy-1"


@pytest.fixture
def backend():
    backend = EvalBackend()
    marker = request_context.set(RequestContext(USER, token_for(USER), backend))
    yield backend
    request_context.reset(marker)


def state(domain, **decision):
    return {"decision": {"domain": domain, **decision}, "session_id": "s-policy", "user_id": USER,
            "run_id": "r-policy", "tool_outputs": [], "tool_count": 0, "execution_records": []}


def call(tool, n=1, **args):
    return {"name": tool, "args": args, "id": f"call-{n}"}


def agent(**settings):
    return ToolAgent(None, EvalStore(), eval_settings(**settings))


def test_meal_domain_allowlist():
    allowed = allowed_tools("meals")
    assert {"create_meals", "list_foods"} <= set(allowed)          # miền của mình + catalog phụ thuộc
    assert "create_foods" not in allowed                            # catalog chỉ được đọc
    assert "delete_trainings" not in allowed                        # miền khác


async def test_tool_outside_domain_is_refused(backend):
    result = await agent().execute_calls(state("meals"), [call("delete_trainings", training_id="x")], [])
    assert result["tool_outputs"][0]["error"] == "Tool is not allowed for this domain"
    assert result["pending_action"] is None
    assert backend.calls == []


async def test_read_only_route_cannot_write(backend):
    result = await agent().execute_calls(state("meals", read_only=True), [call("create_meals", name="x", items=[])], [])
    assert result["tool_outputs"][0]["error"] == "Tool is not allowed for this read-only route"
    assert result["pending_action"] is None


async def test_tool_call_budget(backend):
    calls = [call("list_foods", n, search="phở") for n in range(1, 4)]
    result = await agent(MAX_TOOL_CALLS=2).execute_calls(state("meals"), calls, [])
    outputs = result["tool_outputs"]
    assert [output["ok"] for output in outputs] == [True, True, False]
    assert outputs[2]["error"] == "Tool call limit reached"
    assert result["tool_count"] == 2
    assert len([c for c in backend.calls if c["name"] == "list_foods"]) == 2
