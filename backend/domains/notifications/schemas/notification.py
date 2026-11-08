"""Hợp đồng /api/v2/notifications."""
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

NotificationKind = Literal["briefing", "insight", "praise", "data_quality"]
CATEGORIES: tuple[NotificationKind, ...] = ("briefing", "insight", "praise", "data_quality")
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

    start: ClockTime = "22:00"
    end: ClockTime = "06:30"


class NotificationPreferences(BaseModel):
    """enabled là consent "proactive" (user_consents); phần còn lại lưu ở users.personal_info['notifications']."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    briefing_time: ClockTime = "07:30"
    categories: list[NotificationKind] = Field(default_factory=lambda: list(CATEGORIES))
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    max_per_day: int = Field(default=2, ge=1, le=5)

    @field_validator("categories")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class NotificationPreferencesRead(NotificationPreferences):
    model_config = ConfigDict(extra="ignore")

    timezone: str
