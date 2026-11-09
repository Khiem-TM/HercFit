"""Đồng bộ Google Health định kỳ bên trong tiến trình API (lifespan trong app.py).

Mỗi GOOGLE_HEALTH_SYNC_INTERVAL_MINUTES phút (một nhịp) đồng bộ các kết nối đặt tần suất "hourly" mà
lượt gần nhất đã cũ hơn một giờ; kết nối "open" / "manual" chỉ đồng bộ khi người dùng kích hoạt.
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
            await sync_all(scheduled=True)
        except Exception as exc:
            logger.warning("google_health_sync_loop_error error=%s", type(exc).__name__)
        await asyncio.sleep(settings.GOOGLE_HEALTH_SYNC_INTERVAL_MINUTES * 60)
