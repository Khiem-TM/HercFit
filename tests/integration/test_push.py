"""Đẩy bữa ăn lên Google Health (integrations/google_health/push.py) với Google giả lập."""
from datetime import date, timedelta

from google_fake import FakeGoogle
from payloads import create_food, meal_payload, scalar

from integrations.google_health.push import meal_points, push_pending
from domains.nutrition.models.meals import Meal
from core.database import get_db_session

ZONE = "Asia/Ho_Chi_Minh"
START, END = date.today() - timedelta(days=1), date.today() + timedelta(days=1)


async def _meal(client, headers):
    food = await create_food(client, headers)
    response = await client.post("/api/meals", headers=headers, json=meal_payload(food["id"]))
    assert response.status_code == 201, response.text
    return response.json()


async def test_meal_is_pushed_once(client, make_user):
    user_id, headers = await make_user()
    meal = await _meal(client, headers)
    google = FakeGoogle()

    first = await push_pending(google, user_id, START, END, ZONE)
    second = await push_pending(google, user_id, START, END, ZONE)

    assert first["created"] == 1 and second["created"] == 0
    assert [data_type for data_type, _ in google.created] == ["nutrition-log"]
    names = await scalar("SELECT names FROM google_pushes WHERE record_id = :r", r=meal["id"])
    assert names == [google.created[0][1]]


async def test_point_already_on_google_is_adopted(client, make_user):
    user_id, headers = await make_user()
    meal = await _meal(client, headers)
    google = FakeGoogle()
    # Lần trước đã tạo trên Google nhưng sập trước khi kịp lưu google_pushes.
    async with get_db_session() as session:
        record = await Meal.get_for_user(session, meal["id"], user_id=user_id)
        orphan = google.put("nutrition-log", meal_points(record)[0])

    counts = await push_pending(google, user_id, START, END, ZONE)

    assert counts["adopted"] == 1 and counts["created"] == 0
    assert google.created == []
    assert await scalar("SELECT names FROM google_pushes WHERE record_id = :r", r=meal["id"]) == [orphan]
