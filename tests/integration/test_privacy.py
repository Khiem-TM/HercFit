"""Quyền riêng tư (L5.4): xoá tài khoản do server điều phối và dọn khoá idempotency quá hạn.

Backend gọi endpoint nội bộ của agent (DELETE /internal/users/{id}/conversations, ký HMAC) trước khi xoá tài khoản.
Ở đây endpoint thật của agentic chạy trên app FastAPI riêng, với Runtime và Store thật trên database test; lời gọi
httpx của backend được chuyển tới app đó.
"""
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import SecretStr
from sqlalchemy import text

from agentic.agents.workflow import build_workflow
from agentic.core.app.api.internal import users_router
from agentic.core.app.schemas.request import ChatRequest
from agentic.core.context import RequestContext, request_context
from agentic.services.memory.store import Store
from agentic.services.runtime import Runtime
from core import idempotency, service_auth
from core.database import get_db_session
from core.settings import settings
from core.security import create_delegated_token
from domains.identity.services import privacy_service
from evaluation.adapters.fixtures import EvalBackend, token_for
from evaluation.adapters.graph_runtime import ScriptedModels, eval_settings

SECRET = "privacy-test-service-secret-0001"


async def test_delegated_principal_cannot_export_or_erase_owner_data(client, make_user):
    user_id, headers = await make_user()
    token, _ = create_delegated_token(user_id, consent_version=0)
    delegated = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/profile/export", headers=delegated)).status_code == 403
    assert (await client.post("/api/profile/erase", headers=delegated,
                             json={"confirm_email": f"{user_id}@example.com"})).status_code == 403
    assert await exists(user_id) == 1
    assert (await client.get("/api/profile/export", headers=headers)).status_code == 200


async def test_legacy_agent_header_cannot_export(client, make_user, monkeypatch):
    _, headers = await make_user()
    monkeypatch.setattr(settings, "AGENT_DELEGATION_REQUIRED", False)
    from core.principal import AGENT_CLIENT_HEADER
    response = await client.get("/api/profile/export", headers={**headers, AGENT_CLIENT_HEADER: "agent"})
    assert response.status_code == 403


def agent_app(runtime):
    app = FastAPI()
    app.include_router(users_router.router)
    app.state.settings = SimpleNamespace(AGENT_SERVICE_SECRET=SecretStr(SECRET))
    app.state.runtime = runtime
    return app


@pytest.fixture
def route_to(monkeypatch):
    """Chuyển httpx của backend tới app agent cho trước; cấu hình khoá dịch vụ dùng chung."""
    monkeypatch.setattr(settings, "AGENT_SERVICE_SECRET", SecretStr(SECRET))
    monkeypatch.setattr(settings, "AGENTIC_INTERNAL_URL", "http://agentic")

    def install(app):
        class Routed(httpx.AsyncClient):
            def __init__(self, **kwargs):
                # Như server thật: exception của agent thành phản hồi 500, không ném ngược vào backend.
                super().__init__(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), **kwargs)

        monkeypatch.setattr(privacy_service.httpx, "AsyncClient", Routed)

    return install


async def exists(user_id):
    async with get_db_session() as session:
        return (await session.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id})).scalar_one()


async def test_erasing_the_account_erases_the_conversations(client, make_user, agent_pool, route_to):
    user_id, headers = await make_user()
    store, saver, config = Store(agent_pool, lease_seconds=30, wait_seconds=2), AsyncPostgresSaver(agent_pool), eval_settings()
    runtime = Runtime(build_workflow(ScriptedModels({}), store, saver, None, config), store, saver, config)
    marker = request_context.set(RequestContext(str(user_id), token_for(str(user_id)), EvalBackend()))
    try:
        for _ in range(2):
            await runtime.chat(ChatRequest(message="Xin chào", session_id=uuid4().hex), str(user_id))
    finally:
        request_context.reset(marker)
    assert len(await store.user_session_ids(str(user_id))) == 2
    route_to(agent_app(runtime))

    response = await client.post("/api/profile/erase", json={"confirm_email": f"{user_id}@example.com"},
                                 headers=headers)

    assert response.status_code == 200 and response.json()["erased"] is True
    assert await store.user_session_ids(str(user_id)) == []
    assert await exists(user_id) == 0


@pytest.mark.parametrize("failure", ["agent_error", "not_configured"])
async def test_agent_failure_erases_nothing(client, make_user, route_to, monkeypatch, failure):
    user_id, headers = await make_user()

    async def broken(user):
        raise RuntimeError("store unavailable")

    route_to(agent_app(SimpleNamespace(purge_user=broken)))
    if failure == "not_configured":
        monkeypatch.setattr(settings, "AGENT_SERVICE_SECRET", None)
    response = await client.post("/api/profile/erase", json={"confirm_email": f"{user_id}@example.com"},
                                 headers=headers)
    assert response.status_code == 503
    assert "chưa bị xoá" in response.json()["detail"]
    assert await exists(user_id) == 1


async def test_internal_purge_requires_the_service_signature():
    calls = []

    async def purge(user):
        calls.append(user)
        return {"status": "purged", "sessions": 0}

    user = str(uuid4())
    path = f"/internal/users/{user}/conversations"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_app(SimpleNamespace(purge_user=purge))),
                                 base_url="http://agentic") as http:
        assert (await http.delete(path)).status_code == 401
        other = service_auth.sign(SECRET, "DELETE", path, str(uuid4()))
        assert (await http.delete(path, headers={service_auth.HEADER: other})).status_code == 401
        wrong_key = service_auth.sign("another-secret", "DELETE", path, user)
        assert (await http.delete(path, headers={service_auth.HEADER: wrong_key})).status_code == 401
        signed = service_auth.sign(SECRET, "DELETE", path, user)
        assert (await http.delete(path, headers={service_auth.HEADER: signed})).json()["status"] == "purged"
    assert calls == [user]


async def test_prune_removes_only_expired_idempotency_rows(make_user):
    user_id, _ = await make_user()
    async with get_db_session() as session:
        for key, age in (("old", 31), ("recent", 1)):
            await session.execute(text(
                "INSERT INTO api_idempotency (user_id, key, request_hash, status_code, created_at) "
                "VALUES (:uid, :key, 'h', 200, now() - make_interval(days => :age))"), {"uid": user_id, "key": key,
                                                                                       "age": age})
    async with get_db_session() as session:
        removed = await idempotency.prune(session, 30)
    async with get_db_session() as session:
        keys = (await session.execute(text("SELECT key FROM api_idempotency WHERE user_id = :uid"),
                                      {"uid": user_id})).scalars().all()
        await session.execute(text("DELETE FROM api_idempotency WHERE user_id = :uid"), {"uid": user_id})
    assert keys == ["recent"] and removed >= 1
