"""Phase 2: sửa / xoá bản ghi do HercFit ghi theo trạng thái dòng và kết nối (L2.3), Google giả lập."""
import json
from datetime import date, timedelta

import pytest
from google_fake import FakeGoogle
from payloads import GYM_EXERCISE_ID, TODAY, goal_payload, scalar

from sqlalchemy import text

from core.database import get_db_session
from domains.health_records.types import spec
from integrations.google_health import records, sync
from integrations.google_health.push import push_pending

ZONE = "Asia/Ho_Chi_Minh"
RECORDS = "/api/v2/health/records"
METRICS = spec("weight").write_scope, spec("weight").read_scope
WINDOW = (date.today() - timedelta(days=2), date.today() + timedelta(days=1))


@pytest.fixture
def google(monkeypatch):
    """Google giả cho đường "đã kết nối" của records (không token, không HTTP). Lượt đẩy sau commit bị tắt: kết nối
    giả không có token nên sync thật sẽ đánh dấu cần đăng nhập lại; test gọi push_pending trực tiếp."""
    fake = FakeGoogle()

    async def client(session, user_id, data_type, http):
        return fake

    async def no_sync(user_id, **options):
        return {"status": "skipped"}

    monkeypatch.setattr(records, "_client", client)
    monkeypatch.setattr(sync, "run", no_sync)
    return fake


async def connect(user_id, scopes=METRICS):
    async with get_db_session() as session:
        await session.execute(text(
            "INSERT INTO health_connections (id, user_id, provider_subject, granted_scopes, status) "
            "VALUES (gen_random_uuid(), :u, :s, CAST(:g AS jsonb), 'ACTIVE')"),
            {"u": user_id, "s": f"sub-{user_id}", "g": json.dumps(list(scopes))})


async def weigh(client, headers, kg):
    response = await client.post("/api/body-metrics", headers=headers, json={"weight_kg": kg})
    assert response.status_code == 201, response.text
    return response.json()


async def pushed_weight(client, headers, user_id, google, kg=70.0):
    """Một cân nặng đã có tên Google: ghi khi kết nối rồi đẩy."""
    metric = await weigh(client, headers, kg)
    await push_pending(google, user_id, *WINDOW, ZONE, METRICS)
    name = await scalar("SELECT remote_name FROM health_points WHERE id = :i", i=metric["id"])
    assert not name.startswith("local/")
    return metric, name


async def test_local_row_edit_and_delete_stay_local(client, make_user, google):
    user_id, headers = await make_user()
    record = (await client.post(f"{RECORDS}/hydration", headers=headers, json={"amount_ml": 300})).json()
    name = await scalar("SELECT remote_name FROM health_points WHERE id = :i", i=record["id"])

    edited = await client.patch(f"{RECORDS}/hydration/{record['id']}", headers=headers, json={"amount_ml": 450})
    assert edited.status_code == 200, edited.text
    assert await scalar("SELECT remote_name FROM health_points WHERE id = :i", i=record["id"]) == name
    assert (await scalar("SELECT value FROM health_points WHERE id = :i", i=record["id"]))["amountConsumed"]["milliliters"] == 450

    assert (await client.delete(f"{RECORDS}/hydration/{record['id']}", headers=headers)).status_code == 204
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id = :u", u=user_id) == 0
    assert (google.patched, google.deleted) == ([], [])


async def test_google_row_while_connected_goes_through_google(client, make_user, google):
    user_id, headers = await make_user()
    await connect(user_id)
    metric, name = await pushed_weight(client, headers, user_id, google)

    edited = await client.put(f"/api/body-metrics/{metric['id']}", headers=headers, json={"weight_kg": 69.5})
    assert edited.status_code == 200, edited.text
    assert google.patched == [name]
    assert float(edited.json()["weight_kg"]) == 69.5

    assert (await client.delete(f"/api/body-metrics/{metric['id']}", headers=headers)).status_code == 204
    assert google.deleted == [name]
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id = :u", u=user_id) == 0


async def test_google_row_while_disconnected_becomes_local(client, make_user, google):
    user_id, headers = await make_user()
    await connect(user_id)
    first, _ = await pushed_weight(client, headers, user_id, google, 70.0)
    second, _ = await pushed_weight(client, headers, user_id, google, 71.0)
    assert (await client.delete("/api/integrations/google-health", headers=headers)).status_code == 200

    edited = await client.put(f"/api/body-metrics/{first['id']}", headers=headers, json={"weight_kg": 69.0})
    assert edited.status_code == 200, edited.text
    assert (await scalar("SELECT remote_name FROM health_points WHERE id = :i", i=first["id"])).startswith("local/")
    assert (await client.delete(f"/api/body-metrics/{second['id']}", headers=headers)).status_code == 204
    assert (google.patched, google.deleted) == ([], [])


async def test_disconnect_with_purge_keeps_entered_weights(client, make_user, google):
    user_id, headers = await make_user()
    await connect(user_id)
    for kg in (70.0, 70.5, 71.0):
        await weigh(client, headers, kg)
    await push_pending(google, user_id, *WINDOW, ZONE, METRICS)

    response = await client.delete("/api/integrations/google-health", headers=headers, params={"purge_data": True})
    assert response.status_code == 200, response.text

    weights = (await client.get("/api/body-metrics", headers=headers)).json()
    assert sorted(float(item["weight_kg"]) for item in weights) == [70.0, 70.5, 71.0]
    target, gone = weights[0]["id"], weights[1]["id"]
    assert (await client.put(f"/api/body-metrics/{target}", headers=headers, json={"weight_kg": 68.0})).status_code == 200
    assert (await client.delete(f"/api/body-metrics/{gone}", headers=headers)).status_code == 204
    remaining = (await client.get("/api/body-metrics", headers=headers)).json()
    assert len(remaining) == 2 and 68.0 in [float(item["weight_kg"]) for item in remaining]


async def test_ticking_a_sport_entry_without_google_logs_it(client, make_user):
    user_id, headers = await make_user()
    sport = await client.post("/api/exercises", headers=headers, json={
        "name_vi": "Cầu lông (test)", "kind": "SPORT", "configuration": {"kind": "SPORT", "sport": "badminton"}})
    assert sport.status_code == 201, sport.text
    assert (await client.post("/api/goals/confirm", headers=headers, json=goal_payload())).status_code == 201
    schedule = await client.post("/api/training-plans", headers=headers, json={
        "name": "Lịch tập", "start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=6)).isoformat(),
        "entries": [{"scheduled_date": TODAY.isoformat(), "label": "Cầu lông", "items": [
            {"exercise_id": sport.json()["id"], "prescription": {"kind": "SPORT", "duration_seconds": 3600}}]}]})
    assert schedule.status_code == 201, schedule.text
    plan = schedule.json()
    entry = plan["entries"][0]

    done = await client.post(f"/api/training-plans/{plan['id']}/entries/{entry['id']}/complete", headers=headers)

    assert done.status_code == 200, done.text
    assert not any("Google" in notice for notice in done.json().get("notices", []))
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id = :u AND data_type = 'exercise' "
                        "AND remote_name LIKE 'local/%'", u=user_id) == 1
