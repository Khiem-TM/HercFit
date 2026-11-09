from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field

class FoodChoice(BaseModel):
    """Lựa chọn trên thẻ món thiếu: món catalog tìm được hoặc món riêng vừa tạo, kèm lượng đã ăn."""
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=1, max_length=16)
    food_id: UUID
    quantity: float = Field(gt=0, le=5000)
    unit: Literal['G', 'ML', 'SERVING']

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    # Chấp nhận để tương thích ngược, không bao giờ dùng làm danh tính.
    user_id: str | None = None
    # Nút "Plan" trên ô nhập: normal = ghi nhận dữ liệu; plan = tư vấn chuyên sâu, phân tích, lập kế hoạch tập.
    mode: Literal['normal', 'plan'] = 'normal'
    # Trả lời thẻ món thiếu của lượt trước; server chỉ dùng khi thẻ đó đang mở.
    food_choices: list[FoodChoice] | None = Field(default=None, max_length=5)

class ConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=128)
    action_id: str
    revision: int = Field(ge=1)
    decision: Literal['approve', 'reject']
    # Lịch tập người dùng đã sửa trên thẻ; server kiểm tra lại bằng schema và bản xem trước trước khi duyệt.
    payload: dict[str, Any] | None = None

class FoodNutritionRequest(BaseModel):
    """Tên món riêng người dùng đang tạo; chỉ tên món công khai được gửi tới tra cứu web."""
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
