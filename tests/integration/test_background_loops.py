"""Vòng nền của API (backend/app.py, L5.3): chỉ chạy khi cờ của nó bật; tắt cờ khi worker.py chạy các vòng này."""
import asyncio

import pytest

from app import create_app
from core.settings import settings
from domains.media.services import image_cleanup
from domains.notifications.services import loop as briefing
from integrations.google_health import scheduler

FLAGS = ("GOOGLE_HEALTH_SYNC_LOOP", "DAILY_BRIEFING_LOOP", "IMAGE_CLEANUP_LOOP")


@pytest.mark.parametrize(("enabled", "expected"), [
    (True, {"google_health_sync", "daily_briefing", "image_cleanup"}),
    (False, set()),
])
async def test_api_loops_follow_their_flags(monkeypatch, enabled, expected):
    started = set()

    def fake(name):
        async def run():
            started.add(name)
            await asyncio.Event().wait()
        return run

    monkeypatch.setattr(scheduler, "health_sync_loop", fake("google_health_sync"))
    monkeypatch.setattr(briefing, "daily_briefing_loop", fake("daily_briefing"))
    monkeypatch.setattr(image_cleanup, "cleanup_loop", fake("image_cleanup"))
    monkeypatch.setattr(type(settings), "google_health_configured", property(lambda self: True))
    monkeypatch.setattr(type(settings), "cloudinary_configured", property(lambda self: True))
    for flag in FLAGS:
        monkeypatch.setattr(settings, flag, enabled)
    monkeypatch.setattr(settings, "NOTIFICATION_STREAM", False)
    monkeypatch.setattr(settings, "API_ROUTE_METRICS", False)
    app = create_app()
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
    assert started == expected
