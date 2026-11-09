"""Hợp đồng /api/v2/notifications."""
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# briefing/insight/praise/data_quality/summary: các loại cũ, chỉ còn để đọc thông báo đã gửi trước đây.
NotificationKind = Literal["alert", "review", "reminder", "proposal", "briefing", "insight", "praise", "data_quality",
                           "summary"]
AlertGroup = Literal["heart", "oxygen", "sleep", "weight", "nutrition", "activity"]
ALERT_GROUPS: tuple[AlertGroup, ...] = ("heart", "oxygen", "sleep", "weight", "nutrition", "activity")
ClockTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="HH:MM theo giờ địa phương")]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: NotificationKind
    code: str
    priority: int
    local_date: date
    title: str
    body: str
    payload: dict[str, Any]
    created_at: datetime
    seen_at: datetime | None = None
    expires_at: datetime | None = None


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unread: int


class QuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    start: ClockTime = "22:00"
    end: ClockTime = "06:30"


class NotificationPreferences(BaseModel):
    """enabled là consent "proactive" (user_consents); phần còn lại lưu ở users.personal_info['notifications']."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # Cảnh báo khi chỉ số vượt ngưỡng của bộ luật y tế (domains/analytics/services/health_rules), theo nhóm.
    health_alerts: bool = True
    alert_groups: list[AlertGroup] = Field(default_factory=lambda: list(ALERT_GROUPS))
    # Đánh giá chất lượng ngày của trợ lý: tối đa một lần mỗi ngày, từ giờ người dùng chọn.
    daily_review: bool = True
    daily_review_time: ClockTime = "21:00"
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    # Tính chung mọi loại, trừ cảnh báo khẩn (luôn được gửi, nhưng vẫn chờ hết giờ yên lặng).
    max_per_day: int = Field(default=4, ge=1, le=8)
    # Điều chỉnh lịch tập: đề xuất (người dùng luôn xác nhận qua trợ lý) khi điểm sẵn sàng dưới ngưỡng.
    adjust_on_low_readiness: bool = True
    readiness_threshold: Literal[50, 60, 70] = 60
    # Buổi đã qua ngày mà chưa ghi nhận: hỏi trước khi dời, tự dời sang ngày nghỉ gần nhất, hoặc không làm gì.
    missed_session: Literal["ask", "auto", "none"] = "ask"
    workout_reminder: bool = True
    workout_reminder_time: ClockTime = "17:30"

    @field_validator("alert_groups")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class NotificationPreferencesRead(NotificationPreferences):
    model_config = ConfigDict(extra="ignore")

    timezone: str
