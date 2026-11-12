"""Bản sao dữ liệu Google (domains/health_records/models/health_points.py): replace_window chỉ chạm đúng cửa sổ, đúng loại."""
from datetime import date

from payloads import scalar

from core.database import get_db_session
from domains.health_records.models.health_points import HealthPoint

D = [date(2026, 11, day) for day in range(1, 6)]


def row(user_id, data_type, day, name):
    return {"user_id": user_id, "data_type": data_type, "kind": "daily", "start_at": None, "end_at": None,
            "local_date": day, "value": {"count": 1}, "remote_name": name}


async def test_replace_window_touches_only_its_window_and_type(make_user):
    user_id, _ = await make_user()
    async with get_db_session() as session:
        await HealthPoint.upsert(session, [
            row(user_id, "steps", D[0], "before"),        # trước cửa sổ
            row(user_id, "steps", D[1], "kept"),          # trong cửa sổ, Google vẫn trả về
            row(user_id, "steps", D[2], "gone"),          # trong cửa sổ, Google không còn
            row(user_id, "steps", D[4], "after"),         # từ ngày end trở đi
            row(user_id, "distance", D[2], "other-type"),  # loại khác, cùng ngày
        ])
    async with get_db_session() as session:
        written, removed = await HealthPoint.replace_window(session, user_id, "steps", D[1], D[4],
                                                            [row(user_id, "steps", D[1], "kept")])

    assert (written, removed) == (1, 1)
    names = await scalar("SELECT array_agg(remote_name ORDER BY remote_name) FROM health_points WHERE user_id = :u",
                         u=user_id)
    assert names == ["after", "before", "kept", "other-type"]
