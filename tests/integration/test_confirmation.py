"""Cổng xác nhận lệnh ghi của agent: Runtime.confirm (agentic/services/runtime.py) và Store.authorize.

Runtime và Store thật trên database test (bảng agent tạo bằng migrate_pool, checkpoint LangGraph trên Postgres);
model theo kịch bản và backend giả của bộ eval nên không gọi mạng. Kịch bản là ca `meal_exact_fast_path`.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agentic.agents.workflow import build_workflow
from agentic.core.app.schemas.request import ChatRequest, ConfirmationRequest
from agentic.core.context import RequestContext, request_context
from agentic.services.memory.store import Store
from agentic.services.runtime import Runtime
from evaluation.adapters.fixtures import EvalBackend, token_for
from evaluation.adapters.graph_runtime import ScriptedModels, eval_settings

MESSAGE = "Sáng nay tôi ăn 1 bánh bao nhân thịt"
SCRIPT = {"decision": [{
    "intent": "LOG_FOOD", "next_agent": "tool", "domain": "meals", "action": "tool", "instruction": "Ghi bữa ăn.",
    "meal_log": [{"name": "Bữa sáng", "consumed_at": "2026-11-02T07:30:00+07:00",
                  "items": [{"food": "bánh bao nhân thịt", "quantity": 1, "unit": "SERVING"}]}]}]}


@pytest.fixture
async def agent(agent_pool):
    """(runtime, store, backend, user_id) với một phiên mới; dọn bản ghi agent của user sau test."""
    store = Store(agent_pool, lease_seconds=30, wait_seconds=2)
    saver = AsyncPostgresSaver(agent_pool)
    settings = eval_settings()
    runtime = Runtime(build_workflow(ScriptedModels(SCRIPT), store, saver, None, settings), store, saver, settings)
    user_id, backend = str(uuid4()), EvalBackend()
    marker = request_context.set(RequestContext(user_id, token_for(user_id), backend))
    yield runtime, store, backend, user_id
    request_context.reset(marker)
    async with agent_pool.connection() as conn:
        await conn.execute("DELETE FROM agent_actions WHERE user_id = %s", (user_id,))


async def pending(runtime, user_id):
    session_id = uuid4().hex
    result = await runtime.chat(ChatRequest(message=MESSAGE, session_id=session_id), user_id)
    assert result.status == "pending_confirmation", result.reply
    return session_id, result.pending_action


def confirm(session_id, action, decision="approve", revision=None):
    return ConfirmationRequest(session_id=session_id, action_id=action.action_id,
                               revision=revision or action.revision, decision=decision)


async def test_payload_changed_after_approval_is_refused(agent):
    runtime, store, _, user_id = agent
    _, action = await pending(runtime, user_id)
    await store.set_action(action.action_id, "approved")
    row = (await store.action(action.action_id))["data"]

    assert (await store.authorize(row))["payload_hash"] == row["payload_hash"]
    tampered = {**row, "payload": {**row["payload"], "name": "Bữa tối"}}
    with pytest.raises(HTTPException) as error:
        await store.authorize(tampered)
    assert error.value.status_code == 409


async def test_stale_revision_conflicts(agent):
    runtime, _, backend, user_id = agent
    session_id, action = await pending(runtime, user_id)
    with pytest.raises(HTTPException) as error:
        await runtime.confirm(confirm(session_id, action, revision=action.revision + 1), user_id)
    assert error.value.status_code == 409
    assert backend.writes == []


async def test_expired_action_conflicts(agent, agent_pool):
    runtime, _, backend, user_id = agent
    session_id, action = await pending(runtime, user_id)
    async with agent_pool.connection() as conn:
        await conn.execute("UPDATE agent_actions SET data = jsonb_set(data, '{expires_at}', "
                           "to_jsonb('2000-01-01T00:00:00+00:00'::text)) WHERE action_id = %s", (action.action_id,))
    with pytest.raises(HTTPException) as error:
        await runtime.confirm(confirm(session_id, action), user_id)
    assert error.value.status_code == 409
    assert backend.writes == []


async def test_reject_then_approve_conflicts(agent):
    runtime, _, backend, user_id = agent
    session_id, action = await pending(runtime, user_id)
    await runtime.confirm(confirm(session_id, action, "reject"), user_id)
    with pytest.raises(HTTPException) as error:
        await runtime.confirm(confirm(session_id, action, "approve"), user_id)
    assert error.value.status_code == 409
    assert backend.writes == []


async def test_double_approve_replays_one_write(agent):
    runtime, _, backend, user_id = agent
    session_id, action = await pending(runtime, user_id)
    first = await runtime.confirm(confirm(session_id, action), user_id)
    second = await runtime.confirm(confirm(session_id, action), user_id)

    assert first.status == "completed"
    assert second.model_dump() == first.model_dump()
    assert [write["tool"] for write in backend.writes] == ["create_meals"]
