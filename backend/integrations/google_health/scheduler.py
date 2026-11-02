"""Đồng bộ Google Health định kỳ bên trong tiến trình API (lifespan trong app.py).

Mỗi GOOGLE_HEALTH_SYNC_INTERVAL_MINUTES phút chạy một lượt cho mọi kết nối đang hoạt động.
Nhiều worker cùng chạy vòng lặp vẫn an toàn: advisory lock trong sync.run cho mỗi kết nối
đúng một lượt tại một thời điểm.
"""
import asyncio
import logging

from core.settings import settings
from integrations.google_health.sync import sync_all

logger = logging.getLogger(__name__)


async def health_sync_loop() -> None:
    while True:
        try:
            await sync_all()
        except Exception as exc:
            logger.warning("google_health_sync_loop_error error=%s", type(exc).__name__)
        await asyncio.sleep(settings.GOOGLE_HEALTH_SYNC_INTERVAL_MINUTES * 60)
