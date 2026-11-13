"""Tiến trình nền của backend, tách khỏi API: python worker.py (từ backend/).

Chạy đúng các vòng lặp sẵn có từng nằm trong lifespan của app.py: đồng bộ Google Health, thông báo chủ động (briefing
hằng ngày) và dọn ảnh Cloudinary; thêm vòng dọn khoá idempotency quá hạn mỗi ngày một lần (chỉ chạy ở đây). Vòng nào
thiếu cấu hình thì không chạy, giống điều kiện trong API. Khi dùng worker, API tắt các cờ GOOGLE_HEALTH_SYNC_LOOP,
DAILY_BRIEFING_LOOP, IMAGE_CLEANUP_LOOP (xem docker-compose.prod.yml).

Vòng LISTEN thông báo WebSocket và vòng ghi số đo route ở lại API: chúng phục vụ kết nối WebSocket và bộ đếm request
nằm trong bộ nhớ của chính tiến trình API.
"""

import asyncio
import logging

from agentic.observability import observer
from agentic.observability.logs import configure_from_settings
from core import idempotency
from core.database import close_crud_db_pool, get_async_engine, get_db_session
from core.settings import settings

logger = logging.getLogger(__name__)
IDEMPOTENCY_RETENTION_DAYS = 30
DAY_SECONDS = 24 * 60 * 60


async def idempotency_cleanup_loop():
    """Mỗi ngày một lần: xoá khoá idempotency cũ hơn IDEMPOTENCY_RETENTION_DAYS ngày."""
    while True:
        try:
            async with get_db_session() as session:
                removed = await idempotency.prune(session, IDEMPOTENCY_RETENTION_DAYS)
            logger.info("idempotency_pruned rows=%s", removed)
        except Exception as exc:  # noqa: BLE001 - vòng nền không được chết vì một lần lỗi database
            logger.warning("idempotency_cleanup_error error=%s", type(exc).__name__)
        await asyncio.sleep(DAY_SECONDS)


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
    selected.append(("idempotency_cleanup", idempotency_cleanup_loop))
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
