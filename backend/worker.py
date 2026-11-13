"""Tiến trình nền của backend, tách khỏi API: python worker.py (từ backend/).

Chạy đúng các vòng lặp sẵn có từng nằm trong lifespan của app.py: đồng bộ Google Health, thông báo chủ động (briefing
hằng ngày) và dọn ảnh Cloudinary. Vòng nào thiếu cấu hình thì không chạy, giống điều kiện trong API. Khi dùng worker,
API tắt các cờ GOOGLE_HEALTH_SYNC_LOOP, DAILY_BRIEFING_LOOP, IMAGE_CLEANUP_LOOP (xem docker-compose.prod.yml).

Vòng LISTEN thông báo WebSocket và vòng ghi số đo route ở lại API: chúng phục vụ kết nối WebSocket và bộ đếm request
nằm trong bộ nhớ của chính tiến trình API.
"""

import asyncio
import logging

from agentic.observability import observer
from agentic.observability.logs import configure_from_settings
from core.database import close_crud_db_pool, get_async_engine
from core.settings import settings

logger = logging.getLogger(__name__)


def loops():
    """(tên, hàm vòng lặp) của các vòng nền có đủ cấu hình."""
    selected = []
    if settings.google_health_configured:
        from integrations.google_health.scheduler import health_sync_loop

        selected.append(("google_health_sync", health_sync_loop))
    from domains.notifications.services.loop import daily_briefing_loop

    selected.append(("daily_briefing", daily_briefing_loop))
    if settings.cloudinary_configured:
        from domains.media.services.image_cleanup import cleanup_loop

        selected.append(("image_cleanup", cleanup_loop))
    return selected


async def main():
    configure_from_settings()
    get_async_engine()
    observer()
    selected = loops()
    logger.info("backend_worker_started loops=%s", ",".join(name for name, _ in selected))
    try:
        await asyncio.gather(*(loop() for _, loop in selected))
    finally:
        await observer().close()
        await close_crud_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
