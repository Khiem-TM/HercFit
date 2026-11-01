"""Model đọc cho mục tiêu dinh dưỡng tất định (không để LLM làm tính toán)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel


class EnergyInputsRead(BaseModel):
    weight_kg: float | None
    height_cm: float | None
    age: int | None
    sex: str | None
    activity_level: str | None
    goal_type: str | None
    target_weight_kg: float | None
    target_date: date | None
    trend_weight_kg: float | None


class MacroTargetsRead(BaseModel):
    protein_g: float
    fat_g: float
    carbohydrate_g: float
    fiber_g: float
    protein_g_per_kg: float


class AdaptiveExpenditureRead(BaseModel):
    status: Literal["ok", "insufficient_data"]
    expenditure_kcal: float | None
    average_intake_kcal: float | None
    trend_change_kg: float | None
    span_days: int
    complete_intake_days: int
    weight_points: int
    reasons: list[str]


class TodayIntakeRead(BaseModel):
    date: date
    meal_count: int
    energy_kcal: float
    protein_g: float
    missing_values: int
    remaining_kcal: float | None


class WeightTrendPoint(BaseModel):
    date: date
    weight_kg: float
    trend_kg: float


class NutritionTargetsRead(BaseModel):
    status: Literal["ok", "incomplete_profile"]
    missing: list[str]
    inputs: EnergyInputsRead
    bmr_kcal: float | None
    tdee_kcal: float | None
    target_kcal: float | None
    weekly_change_kg: float | None
    goal_type: str
    activity_factor: float | None
    macros: MacroTargetsRead | None
    adaptive: AdaptiveExpenditureRead
    today: TodayIntakeRead
    weight_trend: list[WeightTrendPoint]
    warnings: list[str]
    method: dict[str, str]
    # "observed": mức vận động lấy từ bước chân của thiết bị vì chưa khai báo.
    activity_level_source: Literal["declared", "observed"] | None = None
    # Trung bình tổng tiêu hao đo bởi thiết bị trên các ngày có đeo đã trọn gần đây (một ước tính).
    device_expenditure_kcal: float | None = None
