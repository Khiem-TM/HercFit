"""Tiến trình nền của backend (backend/worker.py): chạy đúng các vòng có đủ cấu hình, như trong API."""
import pytest

import worker
from core.settings import settings


@pytest.mark.parametrize(("google", "cloudinary", "expected"), [
    (True, True, ["google_health_sync", "daily_briefing", "image_cleanup", "idempotency_cleanup"]),
    (False, True, ["daily_briefing", "image_cleanup", "idempotency_cleanup"]),
    (True, False, ["google_health_sync", "daily_briefing", "idempotency_cleanup"]),
    (False, False, ["daily_briefing", "idempotency_cleanup"]),
])
def test_loops_follow_configuration(monkeypatch, google, cloudinary, expected):
    monkeypatch.setattr(type(settings), "google_health_configured", property(lambda self: google))
    monkeypatch.setattr(type(settings), "cloudinary_configured", property(lambda self: cloudinary))
    selected = worker.loops()
    assert [name for name, _ in selected] == expected
    assert all(callable(loop) for _, loop in selected)
