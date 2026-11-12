"""Payload tổng hợp tạo dữ liệu người dùng qua API thật (không lấy từ người dùng nào)."""
from datetime import date, timedelta

from sqlalchemy import text

from core.database import get_db_session

# Bài tập SPORT hệ thống duy nhất được migration tạo sẵn ("Tập gym (tổng quát)").
GYM_EXERCISE_ID = "54bf874e-3aa7-5d0e-b480-583b7e62ba61"
TODAY = date.today()


async def create_food(client, headers, name="Cơm trắng (test)"):
    response = await client.post("/api/foods", headers=headers, json={
        "name_vi": name, "serving_size": 100, "serving_unit": "G",
        "energy_kcal": 130, "protein_g": 2.7, "carbohydrate_g": 28, "fat_g": 0.3,
    })
    assert response.status_code == 201, response.text
    return response.json()


def meal_payload(food_id, quantity=150):
    return {"name": "Bữa trưa", "timezone": "Asia/Ho_Chi_Minh",
            "items": [{"food_id": food_id, "quantity": quantity, "unit": "G"}]}


def training_payload(minutes=30):
    return {"name": "Tập gym", "timezone": "Asia/Ho_Chi_Minh", "items": [{
        "exercise_id": GYM_EXERCISE_ID,
        "performance": {"kind": "SPORT", "duration_seconds": minutes * 60, "intensity": "MODERATE"}}]}


def goal_payload():
    return {"title": "Giảm 3 kg", "start_date": TODAY.isoformat(),
            "target_date": (TODAY + timedelta(days=90)).isoformat(), "goal_types": ["fat_loss"]}


def plan_payload(goal_id):
    return {"name": "Kế hoạch 12 tuần", "start_date": TODAY.isoformat(),
            "end_date": (TODAY + timedelta(days=84)).isoformat(), "goal_id": goal_id}


def training_plan_payload():
    return {"name": "Lịch tập", "start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=6)).isoformat(),
            "entries": [{"scheduled_date": TODAY.isoformat(), "label": "Gym", "items": [
                {"exercise_id": GYM_EXERCISE_ID, "prescription": {"kind": "SPORT", "duration_seconds": 1800}}]}]}


async def scalar(query: str, **params):
    """Một giá trị đọc thẳng từ database test (để khẳng định số dòng)."""
    async with get_db_session() as session:
        return (await session.execute(text(query), params)).scalar()


async def create_run_exercise(client, headers):
    """Bài chạy riêng của user: catalog test chỉ có "gym tổng quát", mà buổi gym không ghi qua bản ghi sức khoẻ."""
    response = await client.post("/api/exercises", headers=headers, json={
        "name_vi": "Chạy bộ (test)", "kind": "ENDURANCE", "configuration": {"kind": "ENDURANCE", "activity": "RUN"}})
    assert response.status_code == 201, response.text
    return response.json()
