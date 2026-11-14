"""Transcript, execution recovery and model context have independent lifetimes."""
from uuid import UUID, uuid4
from time import monotonic

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from agentic.agents.workflow import build_workflow
from agentic.core.app.schemas.request import ChatRequest
from agentic.core.app.dependencies import authenticated
from agentic.core.context import RequestContext, request_context
from agentic.services.consent_purge import purge_once
from agentic.services.memory.store import Store
from agentic.services.memory.session_memory import SessionMemory
from agentic.services.runtime import Runtime
from agentic.tools.integrations.backend_client import BackendClient
from core.database import get_db_session
from core.security import create_access_token, create_delegated_token
from domains.identity import consent
from evaluation.adapters.fixtures import EvalBackend, token_for
from evaluation.adapters.graph_runtime import ScriptedModels, eval_settings
from test_confirmation import MESSAGE, SCRIPT, confirm

SECRET = "device-health-secret-731"


@pytest.fixture
async def agent(agent_pool, make_user):
    uid, _ = await make_user()
    user_id, backend = str(uid), EvalBackend()
    store, saver, settings = Store(agent_pool), AsyncPostgresSaver(agent_pool), eval_settings()
    runtime = Runtime(build_workflow(ScriptedModels({}), store, saver, None, settings), store, saver, settings)
    marker = request_context.set(RequestContext(user_id, token_for(user_id), backend))
    try:
        yield runtime, store, backend, user_id
    finally:
        await runtime.purge_user(user_id)
        request_context.reset(marker)


async def chat(runtime, user, session_id, message="Xin chào"):
    return await runtime.chat(ChatRequest(message=message, session_id=session_id), user)


async def revoke(user, *, old=False):
    async with get_db_session() as session:
        await consent.grant(session, UUID(user))
        await consent.revoke(session, UUID(user))
        if old:
            await session.execute(text("UPDATE domain_events SET occurred_at=now()-interval '10 days' "
                                       "WHERE user_id=:u AND topic='consent.changed'"), {"u": UUID(user)})


async def test_fifty_turns_survive_checkpoint_deletion_without_redis(agent):
    runtime, store, _, user = agent
    sid = uuid4().hex
    for _ in range(50):
        assert (await chat(runtime, user, sid)).status == "completed"
    history = await runtime.history(sid, user)
    assert history["message_count"] == 100
    assert len({m["id"] for m in history["messages"]}) == 100
    async with store.session(sid, user) as session:
        latest = await runtime.state(session["thread_id"])
        assert len(latest.values["messages"]) < 100
        # Reconciliation is idempotent, and checkpoint expiry cannot remove history.
        await store.archive_snapshot(latest.values)
        for thread in await store.threads(sid):
            if thread != session["thread_id"]:
                await runtime.saver.adelete_thread(thread)
                await store.forget_thread(thread)
    assert (await runtime.history(sid, user))["messages"] == history["messages"]
    assert (await runtime.sessions(user))["sessions"][0]["message_count"] == 100
    with pytest.raises(HTTPException) as exc:
        await runtime.history(sid, str(uuid4()))
    assert exc.value.status_code == 404


async def test_existing_threads_backfill_once_before_pruning(agent):
    runtime, store, _, user = agent
    sid = uuid4().hex
    for _ in range(7):
        await chat(runtime, user, sid)
    async with store.pool.connection() as conn:
        await conn.execute("DELETE FROM agent_transcript_messages WHERE session_id=%s", (sid,))
        await conn.execute("UPDATE agent_sessions SET transcript_migrated=false WHERE session_id=%s", (sid,))
    assert (await runtime.history(sid, user))["message_count"] == 14
    assert (await runtime.history(sid, user))["message_count"] == 14


@pytest.mark.parametrize("cache_unavailable", [False, True])
async def test_revoke_drops_all_context_and_old_checkpoints_but_keeps_transcript(agent, cache_unavailable):
    runtime, store, _, user = agent
    sid = uuid4().hex
    await chat(runtime, user, sid)
    async with store.session(sid, user) as session:
        old_thread, old_generation = session["thread_id"], session["generation"]
        await runtime.graph.aupdate_state(runtime.config(old_thread), {
            "messages": [HumanMessage(content=SECRET), AIMessage(content=SECRET, name="orchestration_agent")],
            "session_memory": {"summary": SECRET, "entities": [{"id": SECRET}]},
            "user_context": {"facts": SECRET}, "tool_outputs": [{"tool": "get_daily_health", "output": SECRET}],
            "graph_context": SECRET,
        })
        await store.save_model_context(sid, user, old_generation, {"summary": SECRET}, 3600)
    await revoke(user)
    if cache_unavailable:
        runtime.memory = SessionMemory(object(), runtime.settings.model_copy(update={"SESSION_MEMORY_MODE": "on"}))
        runtime.memory._down_until = monotonic() + 600
    history = await runtime.history(sid, user)  # Synchronous gate, before the event consumer runs.
    assert SECRET in [m["content"] for m in history["messages"]]
    assert await runtime.saver.aget_tuple(runtime.config(old_thread)) is None
    assert await store.model_context(sid, user, old_generation) is None
    await store.save_model_context(sid, user, old_generation, {"summary": SECRET}, 3600)
    async with store.pool.connection() as conn:
        assert (await (await conn.execute("SELECT count(*) AS n FROM agent_model_context WHERE session_id=%s", (sid,))).fetchone())["n"] == 0
    await chat(runtime, user, sid)
    async with store.session(sid, user) as session:
        latest = await runtime.state(session["thread_id"])
        assert session["generation"] == old_generation + 1
        assert SECRET not in str(latest.values)
        assert latest.values["session_memory"] is None


@pytest.mark.parametrize("approved", [False, True])
async def test_revoke_supersedes_preview_but_can_recover_approved_write(agent, approved):
    runtime, store, backend, user = agent
    runtime.graph = build_workflow(ScriptedModels(SCRIPT), store, runtime.saver, None, runtime.settings)
    sid = uuid4().hex
    result = await chat(runtime, user, sid, MESSAGE)
    action = result.pending_action
    assert action
    if approved:
        await store.set_action(action.action_id, "approved")  # Crash after approval, before a response.
    await revoke(user)
    if approved:
        recovered = await runtime.history(sid, user)
        assert recovered["status"] == "pending_confirmation"
        assert recovered["pending_action"]["action_id"] == action.action_id
        first = await runtime.confirm(confirm(sid, action), user)
        second = await runtime.confirm(confirm(sid, action), user)
        assert first.status == "completed"
        assert first.model_dump() == second.model_dump()
        assert len(backend.writes) == 1
        assert backend.writes[0]["key"] == action.action_id
    else:
        with pytest.raises(HTTPException) as exc:
            await runtime.confirm(confirm(sid, action), user)
        assert exc.value.status_code == 409
        assert (await store.action(action.action_id))["status"] == "superseded"
        assert backend.writes == []


async def test_old_event_is_delivered_and_failed_cache_cleanup_is_retried(agent):
    runtime, store, _, user = agent
    sid = uuid4().hex
    await chat(runtime, user, sid)
    await revoke(user, old=True)

    class Cache:
        failed = True
        calls = 0

        async def forget(self, session_id):
            assert session_id == sid
            self.calls += 1
            return not self.failed

    cache = runtime.memory = Cache()
    with pytest.raises(RuntimeError, match="cleanup is pending"):
        await purge_once(runtime)
    # No model input can read the old generation even while Redis is unavailable.
    async with store.session(sid, user) as session:
        assert session["thread_id"] is None
        assert session["memory_cache_cleanup_pending"] is True
    cache.failed = False
    assert await purge_once(runtime) >= 1
    assert cache.calls == 2
    runtime.memory = None


async def test_cleanup_crash_is_retried_and_clear_erases_all_three_stores(agent, monkeypatch):
    runtime, store, _, user = agent
    sid = uuid4().hex
    await chat(runtime, user, sid)
    async with store.session(sid, user) as session:
        thread = session["thread_id"]
    await revoke(user)
    original = runtime.saver.adelete_thread

    async def unavailable(thread):
        raise RuntimeError("checkpoint store unavailable")
    monkeypatch.setattr(runtime.saver, "adelete_thread", unavailable)
    with pytest.raises(RuntimeError):
        await runtime.history(sid, user)
    monkeypatch.setattr(runtime.saver, "adelete_thread", original)
    assert (await runtime.history(sid, user))["message_count"] == 2
    assert await runtime.saver.aget_tuple(runtime.config(thread)) is None
    await chat(runtime, user, sid)
    async with store.session(sid, user) as session:
        await store.save_model_context(sid, user, session["generation"], {"summary": "new context"}, 3600)
        latest = await runtime.state(session["thread_id"])
    await runtime.clear(sid, user)
    await store.archive_snapshot(latest.values)  # Late reconciliation cannot recreate deleted history.
    assert await store.transcript(sid, user) == []
    assert await store.model_context(sid, user, session["generation"]) is None
    assert await store.threads(sid) == []


async def test_context_ttl_and_generation_are_independent_of_transcript(agent):
    runtime, store, _, user = agent
    sid = uuid4().hex
    await chat(runtime, user, sid)
    async with store.session(sid, user) as session:
        await store.save_model_context(sid, user, session["generation"], {"summary": "expired"}, -1)
        assert await store.model_context(sid, user, session["generation"]) is None
    assert (await runtime.history(sid, user))["message_count"] == 2


async def test_history_http_rejects_delegated_token_and_verifies_owner_token(agent, app, monkeypatch):
    from core.settings import settings
    monkeypatch.setattr(settings, "AGENT_DELEGATION_REQUIRED", False)
    runtime, _, _, user = agent
    sid = uuid4().hex
    await chat(runtime, user, sid)
    chat_app = FastAPI()
    chat_app.state.runtime = runtime
    backend = BackendClient("http://backend", transport=httpx.ASGITransport(app=app))
    chat_app.state.backend = backend

    @chat_app.get("/history")
    async def history(context=Depends(authenticated)):
        return await runtime.history(sid, context.user_id)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=chat_app), base_url="http://agent") as client:
            delegated, _ = create_delegated_token(UUID(user), consent_version=0)
            assert (await client.get("/history", headers={"Authorization": f"Bearer {delegated}"})).status_code == 403
            owner = create_access_token({"sub": user})
            result = await client.get("/history", headers={"Authorization": f"Bearer {owner}"})
            assert result.status_code == 200, result.text
            assert result.json()["message_count"] == 2
            # A forged access claim passes the type prefilter but still fails backend verification.
            forged = owner[:-8] + "invalid0"
            assert (await client.get("/history", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    finally:
        await backend.close()
