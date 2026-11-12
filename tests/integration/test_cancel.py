"""Huỷ lượt chạy (L3.5): Runtime.cancel và POST /chat/runs/{run_id}/cancel.

Runtime và Store thật trên database test, model kịch bản. Một "cổng" (asyncio.Event) giữ lượt chạy ở giữa chừng:
lời gọi model định tuyến (lượt chat) hoặc lệnh ghi tới backend (lượt xác nhận) chờ cổng mở.
"""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agentic.agents.workflow import build_workflow
from agentic.core.app.api.v1 import chat_router
from agentic.core.app.dependencies import authenticated
from agentic.core.app.schemas.request import ChatRequest, ConfirmationRequest
from agentic.core.context import RequestContext, request_context
from agentic.services.memory.store import Store
from agentic.services.runtime import RunCancelled, Runtime
from evaluation.adapters.fixtures import EvalBackend, token_for
from evaluation.adapters.graph_runtime import ScriptedModels, eval_settings

MEAL = "Sáng nay tôi ăn 1 bánh bao nhân thịt"
SCRIPT = {"decision": [{
    "intent": "LOG_FOOD", "next_agent": "tool", "domain": "meals", "action": "tool", "instruction": "Ghi bữa ăn.",
    "meal_log": [{"name": "Bữa sáng", "consumed_at": "2026-11-02T07:30:00+07:00",
                  "items": [{"food": "bánh bao nhân thịt", "quantity": 1, "unit": "SERVING"}]}]}]}


class GatedModels(ScriptedModels):
    """Model định tuyến chờ cổng mở trước khi trả quyết định theo kịch bản."""

    def __init__(self, script, gate, entered):
        super().__init__(script)
        self.gate, self.entered = gate, entered

    def get(self, role):
        model = super().get(role)
        if role != "decision":
            return model
        owner = self

        class Gated:
            metadata = model.metadata

            def with_structured_output(self, schema, **kwargs):
                inner = model.with_structured_output(schema, **kwargs)

                async def ainvoke(messages, **options):
                    owner.entered.set()
                    await owner.gate.wait()
                    return await inner.ainvoke(messages, **options)

                return SimpleNamespace(ainvoke=ainvoke)

            def __getattr__(self, name):
                return getattr(model, name)

        return Gated()


class GatedBackend(EvalBackend):
    """Lệnh ghi create_meals chờ cổng mở (lượt xác nhận đang thực thi)."""

    def __init__(self, gate, entered):
        super().__init__()
        self.gate, self.entered = gate, entered

    async def call(self, name, args, token, key=None):
        if name == "create_meals":
            self.entered.set()
            await self.gate.wait()
        return await super().call(name, args, token, key)


@pytest.fixture
async def setup(agent_pool):
    gate, entered = asyncio.Event(), asyncio.Event()
    store = Store(agent_pool, lease_seconds=30, wait_seconds=2)
    saver = AsyncPostgresSaver(agent_pool)
    settings = eval_settings()
    user_id = str(uuid4())
    backend = GatedBackend(asyncio.Event(), asyncio.Event())
    backend.gate.set()
    runtime = Runtime(build_workflow(GatedModels(SCRIPT, gate, entered), store, saver, None, settings),
                      store, saver, settings)
    marker = request_context.set(RequestContext(user_id, token_for(user_id), backend))
    yield SimpleNamespace(runtime=runtime, backend=backend, gate=gate, entered=entered, user_id=user_id)
    gate.set()
    request_context.reset(marker)
    async with agent_pool.connection() as conn:
        await conn.execute("DELETE FROM agent_actions WHERE user_id = %s", (user_id,))


async def start_chat(env, session_id):
    events = []

    async def emit(event):
        events.append(event)

    task = asyncio.create_task(env.runtime.chat(ChatRequest(message=MEAL, session_id=session_id), env.user_id, emit))
    await asyncio.wait_for(env.entered.wait(), 10)
    [run_id] = [event["run_id"] for event in events if event["type"] == "run"]
    return task, run_id


async def test_cancel_stops_the_run_and_frees_the_session(setup):
    session_id = uuid4().hex
    task, run_id = await start_chat(setup, session_id)
    assert run_id in setup.runtime.running

    setup.runtime.cancel(run_id, setup.user_id)

    with pytest.raises(RunCancelled):
        await asyncio.wait_for(task, 10)
    assert run_id not in setup.runtime.running
    assert setup.backend.writes == []
    # Lease của cuộc trò chuyện đã được nhả: tin nhắn kế tiếp chạy ngay, không gặp "đang xử lý lượt khác".
    setup.gate.set()
    result = await setup.runtime.chat(ChatRequest(message=MEAL, session_id=session_id), setup.user_id)
    assert result.status == "pending_confirmation"


async def test_other_user_or_unknown_run_gets_404(setup):
    task, run_id = await start_chat(setup, uuid4().hex)
    for run, user in ((run_id, str(uuid4())), (str(uuid4()), setup.user_id)):
        with pytest.raises(HTTPException) as error:
            setup.runtime.cancel(run, user)
        assert error.value.status_code == 404
    setup.gate.set()
    assert (await asyncio.wait_for(task, 10)).status == "pending_confirmation"


async def test_cancel_while_executing_an_approved_write_is_refused(setup):
    setup.gate.set()
    session_id = uuid4().hex
    pending = await setup.runtime.chat(ChatRequest(message=MEAL, session_id=session_id), setup.user_id)
    action = pending.pending_action
    setup.backend.gate.clear()
    confirm = asyncio.create_task(setup.runtime.confirm(ConfirmationRequest(
        session_id=session_id, action_id=action.action_id, revision=action.revision, decision="approve"),
        setup.user_id))
    await asyncio.wait_for(setup.backend.entered.wait(), 10)

    with pytest.raises(HTTPException) as error:
        setup.runtime.cancel(pending.run_id, setup.user_id)
    assert error.value.status_code == 409

    setup.backend.gate.set()
    result = await asyncio.wait_for(confirm, 10)
    assert result.status == "completed"
    assert [write["tool"] for write in setup.backend.writes] == ["create_meals"]


@pytest.mark.parametrize(("raised", "status"), [(None, 202), (404, 404), (409, 409)])
async def test_cancel_endpoint_maps_runtime_errors(raised, status):
    calls = []

    def cancel(run_id, user_id):
        calls.append((run_id, user_id))
        if raised:
            raise HTTPException(raised, "x")

    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/v1")
    app.state.runtime = SimpleNamespace(cancel=cancel)
    app.dependency_overrides[authenticated] = lambda: SimpleNamespace(user_id="u-1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/runs/r-1/cancel")
    assert response.status_code == status
    assert calls == [("r-1", "u-1")]


async def test_stream_sends_run_id_first_and_ends_cancelled():
    async def chat(payload, user_id, emit=None):
        await emit({"type": "run", "run_id": "r-1"})
        raise RunCancelled()

    async def consume_turn(*args, **kwargs):
        return True

    settings = SimpleNamespace(SSE_HEARTBEAT_SECONDS=15, AGENT_RATE_LIMIT_PER_MINUTE=1000,
                               AGENT_DAILY_TURN_LIMIT=1000, AGENT_DAILY_TOKEN_LIMIT=10**9)
    app = FastAPI()
    app.include_router(chat_router.router, prefix="/api/v1")
    app.state.runtime = SimpleNamespace(chat=chat, settings=settings, store=SimpleNamespace(consume_turn=consume_turn))
    app.dependency_overrides[authenticated] = lambda: RequestContext("u-1", "t", None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat/stream", json={"message": "xin chào", "session_id": "s-1"})
    frames = [line[6:] for line in response.text.split("\n") if line.startswith("data: ")]
    assert frames == ['{"type": "run", "run_id": "r-1"}', '{"type": "cancelled"}', "[DONE]"]
