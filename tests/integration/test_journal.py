"""Nhật ký bất biến (domains/shared/models/journal.py): sửa tạo snapshot mới, phiên bản lạc quan."""
from payloads import create_food, meal_payload


async def _meal(client, headers):
    food = await create_food(client, headers)
    response = await client.post("/api/meals", headers=headers, json=meal_payload(food["id"]))
    assert response.status_code == 201, response.text
    return food, response.json()


async def test_replace_creates_new_snapshot(client, make_user):
    _, headers = await make_user()
    food, meal = await _meal(client, headers)

    replaced = await client.put(f"/api/meals/{meal['id']}", headers=headers,
                                json={**meal_payload(food["id"], 200), "expected_version_id": meal["version_id"]})

    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["id"] != meal["id"]
    old = await client.get(f"/api/meals/{meal['id']}", headers=headers, params={"include_inactive": True})
    assert old.status_code == 200
    assert old.json()["is_active"] is False
    assert (await client.get(f"/api/meals/{meal['id']}", headers=headers)).status_code == 404


async def test_stale_version_conflicts(client, make_user):
    _, headers = await make_user()
    food, meal = await _meal(client, headers)
    response = await client.put(f"/api/meals/{meal['id']}", headers=headers,
                                json={**meal_payload(food["id"], 200), "expected_version_id": meal["version_id"] + 1})
    assert response.status_code == 409


async def test_replace_after_delete_conflicts(client, make_user):
    _, headers = await make_user()
    food, meal = await _meal(client, headers)
    deleted = await client.delete(f"/api/meals/{meal['id']}", headers=headers,
                                  params={"expected_version_id": meal["version_id"]})
    assert deleted.status_code == 204
    response = await client.put(f"/api/meals/{meal['id']}", headers=headers,
                                json={**meal_payload(food["id"], 200), "expected_version_id": meal["version_id"]})
    assert response.status_code == 409
