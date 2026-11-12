"""Idempotency-Key trên lệnh ghi (core/idempotency.py)."""
from uuid import uuid4

from payloads import create_food, meal_payload, scalar


async def test_same_key_same_body_replays_one_record(client, make_user):
    user_id, headers = await make_user()
    food = await create_food(client, headers)
    keyed = {**headers, "Idempotency-Key": str(uuid4())}

    first = await client.post("/api/meals", headers=keyed, json=meal_payload(food["id"]))
    second = await client.post("/api/meals", headers=keyed, json=meal_payload(food["id"]))

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert await scalar("SELECT count(*) FROM meals WHERE user_id = :u", u=user_id) == 1
    assert await scalar("SELECT count(*) FROM api_idempotency WHERE user_id = :u AND key = :k",
                        u=user_id, k=keyed["Idempotency-Key"]) == 1


async def test_same_key_different_body_conflicts(client, make_user):
    user_id, headers = await make_user()
    food = await create_food(client, headers)
    keyed = {**headers, "Idempotency-Key": str(uuid4())}

    assert (await client.post("/api/meals", headers=keyed, json=meal_payload(food["id"], 150))).status_code == 201
    retry = await client.post("/api/meals", headers=keyed, json=meal_payload(food["id"], 200))

    assert retry.status_code == 409
    assert await scalar("SELECT count(*) FROM meals WHERE user_id = :u", u=user_id) == 1


async def test_failed_handler_leaves_no_ledger_row(client, make_user):
    user_id, headers = await make_user()
    keyed = {**headers, "Idempotency-Key": str(uuid4())}

    failed = await client.post("/api/meals", headers=keyed, json=meal_payload(str(uuid4())))  # món không tồn tại

    assert failed.status_code >= 400
    assert await scalar("SELECT count(*) FROM api_idempotency WHERE user_id = :u", u=user_id) == 0
    assert await scalar("SELECT count(*) FROM meals WHERE user_id = :u", u=user_id) == 0
