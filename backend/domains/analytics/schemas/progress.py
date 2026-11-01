"""So sánh chỉ đọc; không lưu bộ đếm tiến độ hay ước tính calo nào."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from domains.shared.schemas.common import ReadSchema


class MetricProgress(ReadSchema):
    target: Decimal | None = None
    actual: Decimal | None
    known_total: Decimal
    missing_count: int = Field(ge=0)


class DailyProgressRead(ReadSchema):
    date: date
    meal_count: int
    training_count: int
    calories_in: MetricProgress
    exercise_calories: MetricProgress
    protein_g: MetricProgress
    carbohydrate_g: MetricProgress
    fat_g: MetricProgress
    fiber_g: MetricProgress
    # Tải session-RPE (Foster); giúp tư vấn dinh dưỡng điều chỉnh theo áp lực tập luyện.
    training_load: Decimal = Decimal(0)
    calories_out_target: Decimal | None
    # Tổng tiêu hao mỗi ngày đo bởi thiết bị đã kết nối (Google Health); riêng nhật ký tập
    # không đo được nó, nên khi không có thiết bị thì giá trị là null.
    calories_out_actual: Decimal | None = None


class ProgressRead(ReadSchema):
    timezone: str
    start_date: date
    end_date: date
    days: list[DailyProgressRead]


class PlanProgressRead(ProgressRead):
    plan_id: UUID
