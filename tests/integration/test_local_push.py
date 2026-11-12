"""Phase 2: bản ghi cục bộ (remote_name "local/...") được đẩy lên Google sau commit (L2.2), Google giả lập."""
import asyncio
from datetime import date, timedelta

from google_fake import FakeGoogle
from payloads import scalar

from core.database import get_db_session
from domains.health_records.models.health_points import HealthPoint
from domains.health_records.types import spec
from integrations.google_health import kinds, sync
from integrations.google_health.client import GoogleHealthError
from integrations.google_health.pull import pull
from integrations.google_health.push import push_pending

ZONE = "Asia/Ho_Chi_Minh"
START, END = date.today() - timedelta(days=2), date.today() + timedelta(days=1)
NUTRITION = [spec("hydration-log").read_scope, spec("hydration-log").write_scope]


async def log_water(client, headers, ml=300):
    response = await client.post("/api/v2/health/records/hydration", headers=headers, json={"amount_ml": ml})
    assert response.status_code == 201, response.text
    return response.json()


async def remote_names(user_id):
    return await scalar("SELECT array_agg(remote_name ORDER BY remote_name) FROM health_points WHERE user_id = :u",
                        u=user_id)


async def test_local_row_is_created_once_and_renamed(client, make_user):
    user_id, headers = await make_user()
    await log_water(client, headers)
    google = FakeGoogle()

    first = await push_pending(google, user_id, START, END, ZONE, NUTRITION)
    second = await push_pending(google, user_id, START, END, ZONE, NUTRITION)

    assert (first["created"], second["created"]) == (1, 0)
    [(data_type, name)] = google.created
    assert data_type == "hydration-log"
    assert await remote_names(user_id) == [name]


async def test_point_created_before_crash_is_adopted(client, make_user):
    user_id, headers = await make_user()
    record = await log_water(client, headers)
    google = FakeGoogle()
    # Lần trước đã tạo trên Google nhưng sập trước khi đổi tên; lần pull sau đó đọc nó về thành dòng riêng.
    orphan = google.put("hydration-log", {"dataSource": kinds.MANUAL, "hydrationLog": record["value"]})
    await pull(google, user_id, NUTRITION, START, END, ZONE)
    assert len(await remote_names(user_id)) == 2

    counts = await push_pending(google, user_id, START, END, ZONE, NUTRITION)

    assert (counts["adopted"], counts["created"]) == (1, 0)
    assert google.created == []
    assert await remote_names(user_id) == [orphan]


async def test_next_pull_does_not_duplicate(client, make_user):
    user_id, headers = await make_user()
    await log_water(client, headers)
    google = FakeGoogle()
    await push_pending(google, user_id, START, END, ZONE, NUTRITION)

    await pull(google, user_id, NUTRITION, START, END, ZONE)

    [(_, name)] = google.created
    assert await remote_names(user_id) == [name]
    assert await scalar("SELECT bool_and(written_by_hercfit) FROM health_points WHERE user_id = :u", u=user_id)


async def test_without_write_scope_or_connection_nothing_is_sent(client, make_user):
    user_id, headers = await make_user()
    await log_water(client, headers)
    google = FakeGoogle()

    counts = await push_pending(google, user_id, START, END, ZONE, granted=[spec("hydration-log").read_scope])

    assert counts["created"] == 0 and google.created == []
    assert (await sync.run(user_id, push_only=True))["status"] == "not_connected"
    [name] = await remote_names(user_id)
    assert name.startswith("local/")


async def test_failure_on_one_row_does_not_block_others(client, make_user, monkeypatch):
    user_id, headers = await make_user()
    await log_water(client, headers, 300)
    await log_water(client, headers, 400)
    google = FakeGoogle()
    real_create = google.create_point
    calls = []

    async def flaky(data_type, point):
        calls.append(point)
        if len(calls) == 1:
            raise GoogleHealthError("provider_error", 503)
        return await real_create(data_type, point)

    monkeypatch.setattr(google, "create_point", flaky)
    counts = await push_pending(google, user_id, START, END, ZONE, NUTRITION)

    assert (counts["failed"], counts["created"]) == (1, 1)
    names = await remote_names(user_id)
    assert sum(name.startswith("local/") for name in names) == 1
    async with get_db_session() as session:
        assert len((await session.execute(HealthPoint.__table__.select().where(
            HealthPoint.user_id == user_id))).all()) == 2


async def test_create_schedules_a_push_after_commit(client, make_user, monkeypatch):
    user_id, headers = await make_user()
    scheduled = []

    async def fake_run(uid, **options):
        scheduled.append((uid, options))
        return {"status": "ok"}

    monkeypatch.setattr(sync, "run", fake_run)
    await log_water(client, headers)
    await asyncio.sleep(0)  # task được tạo trong hook after_commit

    assert scheduled == [(user_id, {"push_only": True})]
