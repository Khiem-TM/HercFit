"""Deterministic interleavings: no sleeps or real provider requests."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google_fake import FakeGoogle
from payloads import scalar
from sqlalchemy import text

from core.database import get_db_session
from domains.health_records.types import spec
from integrations.google_health import fencing, sync, tokens
from integrations.google_health.client import GoogleHealthError, ReauthRequired
from integrations.google_health.connection import HealthConnectionService, purge_device_data
from integrations.google_health.models import HealthConnection
from integrations.google_health.pull import pull
from integrations.google_health.push import push_pending

ZONE = "Asia/Ho_Chi_Minh"
WINDOW = date.today() - timedelta(days=2), date.today() + timedelta(days=1)
SCOPES = [spec("hydration-log").read_scope, spec("hydration-log").write_scope]


@pytest.fixture(autouse=True)
def no_background_sync(monkeypatch):
    async def noop(*args, **kwargs):
        return {"status": "skipped"}
    monkeypatch.setattr(sync, "run", noop)


@pytest.mark.parametrize("mutation", ["purge", "disconnect", "disconnect_reconnect"])
async def test_old_fetch_cannot_commit_after_connection_changes(client, make_user, mutation):
    user_id, headers = await make_user()
    record = (await client.post("/api/v2/health/records/hydration", headers=headers,
                                json={"amount_ml": 300})).json()
    google = FakeGoogle()
    google.put("hydration-log", {"hydrationLog": record["value"]})
    async with get_db_session() as session:
        await session.execute(text("DELETE FROM health_points WHERE user_id=:u"), {"u": user_id})
        connection = HealthConnection(user_id=user_id, provider_subject=str(user_id), status="ACTIVE")
        session.add(connection)
        await session.flush()
        fence = fencing.SyncFence(connection.id, connection.sync_generation)
    fetched, release = asyncio.Event(), asyncio.Event()
    original = google.list_page

    async def paused(*args, **kwargs):
        response = await original(*args, **kwargs)
        fetched.set()
        await release.wait()
        return response
    google.list_page = paused

    async def worker():
        marker = fencing.current.set(fence)
        try:
            await pull(google, user_id, SCOPES, *WINDOW, ZONE)
            await sync._finish(fence.connection_id, datetime.now(timezone.utc), profile={"age": 99})
        finally:
            fencing.current.reset(marker)

    task = asyncio.create_task(worker())
    try:
        await asyncio.wait_for(fetched.wait(), 5)
        async with get_db_session() as session:
            if mutation == "purge":
                await purge_device_data(session, user_id)
            else:
                await HealthConnectionService(session, SimpleNamespace(id=user_id)).disconnect(purge_data=True)
                if mutation == "disconnect_reconnect":
                    row = await session.get(HealthConnection, fence.connection_id)
                    row.status = "ACTIVE"
                    row.sync_generation += 1
    finally:
        release.set()
    with pytest.raises(fencing.SyncSuperseded):
        await asyncio.wait_for(task, 5)
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id=:u", u=user_id) == 0
    assert await scalar("SELECT provider_profile FROM health_connections WHERE user_id=:u", u=user_id) == {}
    assert await scalar("SELECT sync_cursor FROM health_connections WHERE user_id=:u", u=user_id) == {}
    # Even the status/profile finalizer cannot resurrect an invalidated generation.
    marker = fencing.current.set(fence)
    try:
        with pytest.raises(fencing.SyncSuperseded):
            await sync._finish(fence.connection_id, datetime.now(timezone.utc), profile={"age": 99})
    finally:
        fencing.current.reset(marker)


@pytest.mark.parametrize("mutation", ["edit", "delete", "edit_cleanup_failure"])
async def test_local_mutation_during_push_cannot_acknowledge_old_value(client, make_user, mutation):
    user_id, headers = await make_user()
    record = (await client.post("/api/v2/health/records/hydration", headers=headers,
                                json={"amount_ml": 300})).json()
    google = FakeGoogle()
    posted, release = asyncio.Event(), asyncio.Event()
    original_create, original_delete = google.create_point, google.batch_delete

    async def paused(*args, **kwargs):
        result = await original_create(*args, **kwargs)
        posted.set()
        await release.wait()
        return result
    google.create_point = paused
    task = asyncio.create_task(push_pending(google, user_id, *WINDOW, ZONE, SCOPES))
    try:
        await asyncio.wait_for(posted.wait(), 5)
        path = f"/api/v2/health/records/hydration/{record['id']}"
        if mutation == "delete":
            assert (await client.delete(path, headers=headers)).status_code == 204
        else:
            response = await client.patch(path, headers=headers, json={"amount_ml": 450})
            assert response.status_code == 200, response.text
        if mutation == "edit_cleanup_failure":
            async def failed(*args, **kwargs):
                raise GoogleHealthError("temporarily_down", 503)
            google.batch_delete = failed
    finally:
        release.set()
    if mutation == "edit_cleanup_failure":
        with pytest.raises(GoogleHealthError):
            await asyncio.wait_for(task, 5)
    else:
        await asyncio.wait_for(task, 5)
    stale_name = google.created[0][1]
    await pull(google, user_id, SCOPES, *WINDOW, ZONE)
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id=:u AND remote_name=:n",
                        u=user_id, n=stale_name) == 0
    google.create_point, google.batch_delete = original_create, original_delete
    await push_pending(google, user_id, *WINDOW, ZONE, SCOPES)
    await pull(google, user_id, SCOPES, *WINDOW, ZONE)
    assert stale_name in google.deleted
    assert await scalar("SELECT count(*) FROM health_push_cleanup WHERE user_id=:u", u=user_id) == 0
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id=:u", u=user_id) == (0 if mutation == "delete" else 1)
    if mutation != "delete":
        value = await scalar("SELECT value FROM health_points WHERE user_id=:u", u=user_id)
        assert value["amountConsumed"]["milliliters"] == 450
        assert len(google.created) == 2


@pytest.mark.parametrize("reconnect", [False, True])
async def test_refresh_response_cannot_restore_credentials_of_old_connection(make_user, monkeypatch, reconnect):
    user_id, _ = await make_user()
    async with get_db_session() as session:
        row = HealthConnection(user_id=user_id, provider_subject=str(user_id), status="ACTIVE",
                               refresh_token_enc="old-refresh")
        session.add(row)
        await session.flush()
        connection_id, generation = row.id, row.sync_generation
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(*args):
        started.set()
        await release.wait()
        return {"access_token": "stale-access", "refresh_token": "stale-refresh"}
    monkeypatch.setattr(tokens, "decrypt_secret", lambda value: value)
    monkeypatch.setattr(tokens, "encrypt_secret", lambda value: value)
    monkeypatch.setattr(tokens.oauth, "refresh_access_token", delayed)
    task = asyncio.create_task(tokens.access_token(connection_id, None))
    try:
        await asyncio.wait_for(started.wait(), 5)
        async with get_db_session() as session:
            row = await session.get(HealthConnection, connection_id, with_for_update=True)
            row.sync_generation += 1
            row.status = "ACTIVE" if reconnect else "REVOKED"
            row.access_token_enc = "new-access" if reconnect else None
            row.refresh_token_enc = "new-refresh" if reconnect else None
    finally:
        release.set()
    with pytest.raises(ReauthRequired):
        await asyncio.wait_for(task, 5)
    await tokens.mark_reauth(connection_id, generation=generation)
    async with get_db_session() as session:
        row = await session.get(HealthConnection, connection_id)
        assert row.status == ("ACTIVE" if reconnect else "REVOKED")
        assert row.access_token_enc == ("new-access" if reconnect else None)
        assert row.refresh_token_enc == ("new-refresh" if reconnect else None)
