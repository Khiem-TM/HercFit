"""Ảnh chụp ngữ cảnh trợ lý: những gì HercFit đã biết về người dùng."""
from typing import Any

from pydantic import BaseModel


class AssistantContextRead(BaseModel):
    generated_at: str
    timezone: str
    today: str
    profile: dict[str, Any]
    body: dict[str, Any]
    goal: dict[str, Any] | None
    athlete: dict[str, Any]
    running: dict[str, Any]
    training_4w: dict[str, Any]
    inventory: dict[str, Any]
    # Các dữ kiện huấn luyện chưa có giá trị đã lưu; chỉ những dữ kiện này trợ lý mới được hỏi người dùng.
    missing: list[str]
