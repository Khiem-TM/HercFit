"""Phase 2: dữ liệu người dùng nhập được lưu trong HercFit trước, không cần kết nối Google (L2.1)."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from payloads import create_run_exercise, scalar

from core.database import get_db_session
from domains.health_records.models.health_points import HealthPoint
from integrations.google_health.connection import purge_device_data

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
RECORDS = "/api/v2/health/records"


async def log_all(client, headers):
    """Một buổi chạy, 500 ml nước và một giấc ngủ, ghi qua API như agent làm."""
    now = datetime.now(timezone.utc)
    exercise = await create_run_exercise(client, headers)
    responses = [
        await client.post(f"{RECORDS}/exercise", headers=headers, json={
            "name": "Chạy sáng", "started_at": (now - timedelta(hours=2)).isoformat(), "exercise_id": exercise["id"],
            "performance": {"kind": "ENDURANCE", "duration_seconds": 1800, "distance_meters": 5000}}),
        await client.post(f"{RECORDS}/hydration", headers=headers, json={"amount_ml": 500}),
        await client.post(f"{RECORDS}/sleep", headers=headers, json={
            "started_at": (now - timedelta(hours=9)).isoformat(), "ended_at": (now - timedelta(hours=2)).isoformat()}),
    ]
    assert [response.status_code for response in responses] == [201, 201, 201], [r.text for r in responses]
    return [response.json() for response in responses]


async def test_unconnected_user_logs_run_water_sleep(client, make_user):
    user_id, headers = await make_user()
    await log_all(client, headers)

    names = await scalar("SELECT array_agg(remote_name) FROM health_points WHERE user_id = :u AND written_by_hercfit",
                         u=user_id)
    assert len(names) == 3 and all(name.startswith("local/") for name in names)

    overview = (await client.get("/api/health/overview", headers=headers)).json()
    assert overview["connected"] is False
    assert overview["activity"]["workouts"] == 1
    assert overview["sleep"]["nights"] == 1
    today = datetime.now(ZONE).date().isoformat()
    daily = (await client.get("/api/health/daily", headers=headers,
                              params={"start_date": today, "end_date": today})).json()
    assert sum(float(day.get("hydration_ml") or 0) for day in daily) == 500


async def test_replace_window_keeps_local_rows(client, make_user):
    user_id, headers = await make_user()
    await log_all(client, headers)
    today = datetime.now(ZONE).date()

    async with get_db_session() as session:
        for data_type in ("exercise", "hydration-log", "sleep"):
            # Google trả về cửa sổ rỗng: điểm cục bộ chưa đẩy vẫn phải còn.
            await HealthPoint.replace_window(session, user_id, data_type, today - timedelta(days=2),
                                             today + timedelta(days=1), [])

    assert await scalar("SELECT count(*) FROM health_points WHERE user_id = :u", u=user_id) == 3


async def test_purge_keeps_hercfit_rows(client, make_user):
    user_id, headers = await make_user()
    await log_all(client, headers)
    async with get_db_session() as session:
        await HealthPoint.upsert(session, [{
            "user_id": user_id, "data_type": "steps", "kind": "daily", "start_at": None, "end_at": None,
            "local_date": date.today(), "value": {"count": 4200}, "remote_name": "device-steps"}])

    async with get_db_session() as session:
        counts = await purge_device_data(session, user_id)

    assert counts["health_points"] == 1
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id = :u AND written_by_hercfit",
                        u=user_id) == 3
    assert await scalar("SELECT count(*) FROM health_points WHERE user_id = :u AND NOT written_by_hercfit",
                        u=user_id) == 0
