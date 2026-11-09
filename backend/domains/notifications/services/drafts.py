"""Bản nháp thông báo và tiện ích giờ địa phương dùng chung cho cảnh báo, đánh giá ngày và nhắc lịch tập.

dedup_key quyết định "đã báo chưa", nên gọi lại bao nhiêu lần cũng không lặp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from domains.notifications.schemas.notification import NotificationPreferences


@dataclass(frozen=True)
class Draft:
    kind: str
    code: str
    priority: int
    dedup_key: str
    title: str
    body: str
    payload: dict[str, Any] = field(default_factory=dict)
    # Hết hạn sau chừng này ngày kể từ ngày của thông báo.
    ttl_days: int = 2
    # Cảnh báo khẩn: không tính vào giới hạn mỗi ngày (vẫn chờ hết giờ yên lặng).
    urgent: bool = False


def clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def quiet(prefs: NotificationPreferences, local_now: datetime) -> bool:
    if not prefs.quiet_hours.enabled:
        return False
    start, end, now = clock(prefs.quiet_hours.start), clock(prefs.quiet_hours.end), local_now.time()
    if start == end:
        return False
    return start <= now < end if start < end else (now >= start or now < end)
