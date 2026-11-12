"""Cách ly người dùng: user B không đọc, sửa hay xoá được bản ghi của user A theo id (luôn 404)."""
import pytest
from payloads import (
    create_food,
    goal_payload,
    meal_payload,
    plan_payload,
    training_payload,
    training_plan_payload,
)


async def _post(client, headers, path, payload):
    response = await client.post(path, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def seed_meal(client, headers):
    food = await create_food(client, headers)
    meal = await _post(client, headers, "/api/meals", meal_payload(food["id"]))
    return f"/api/meals/{meal['id']}", ("put", {**meal_payload(food["id"]), "expected_version_id": meal["version_id"]}), \
        {"expected_version_id": meal["version_id"]}


async def seed_training(client, headers):
    training = await _post(client, headers, "/api/trainings", training_payload())
    return f"/api/trainings/{training['id']}", \
        ("put", {**training_payload(45), "expected_version_id": training["version_id"]}), \
        {"expected_version_id": training["version_id"]}


async def seed_body_metric(client, headers):
    metric = await _post(client, headers, "/api/body-metrics", {"weight_kg": 70.5})
    return f"/api/body-metrics/{metric['id']}", ("put", {"weight_kg": 70.0}), {}


async def seed_goal(client, headers):
    goal = await _post(client, headers, "/api/goals/confirm", goal_payload())
    return f"/api/goals/{goal['id']}", ("patch", {"title": "Giảm 4 kg", "expected_version_id": goal["version_id"]}), {}


async def seed_plan(client, headers):
    goal = await _post(client, headers, "/api/goals/confirm", goal_payload())
    plan = await _post(client, headers, "/api/plans", plan_payload(goal["id"]))
    return f"/api/plans/{plan['id']}", ("put", {**plan_payload(goal["id"]), "expected_version_id": plan["version_id"]}), \
        {"expected_version_id": plan["version_id"]}


async def seed_training_plan(client, headers):
    await _post(client, headers, "/api/goals/confirm", goal_payload())  # lịch tập cần một mục tiêu đang thực hiện
    schedule = await _post(client, headers, "/api/training-plans", training_plan_payload())
    return f"/api/training-plans/{schedule['id']}", \
        ("put", {**training_plan_payload(), "expected_version_id": schedule["version_id"]}), \
        {"expected_version_id": schedule["version_id"]}


SEEDS = [seed_meal, seed_training, seed_body_metric, seed_goal, seed_plan, seed_training_plan]


@pytest.mark.parametrize("seed", SEEDS, ids=[seed.__name__.removeprefix("seed_") for seed in SEEDS])
async def test_other_user_gets_404(client, make_user, seed):
    _, owner = await make_user("A")
    _, other = await make_user("B")
    path, (method, body), delete_params = await seed(client, owner)

    assert (await client.get(path, headers=owner)).status_code == 200
    assert (await client.get(path, headers=other)).status_code == 404
    assert (await client.request(method.upper(), path, headers=other, json=body)).status_code == 404
    assert (await client.delete(path, headers=other, params=delete_params)).status_code == 404
    # Bản ghi của A vẫn nguyên sau các lần thử của B.
    assert (await client.get(path, headers=owner)).status_code == 200
