"""Chạy một lần bằng `python -m domains.media.services.image_cleanup`; lên lịch vài phút một lần."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from core.database import get_db_session, close_crud_db_pool
from domains.media.models.media import ImageCleanup
from domains.media.services.cloudinary_images import CloudinaryImages
from domains.media.services.media_service import MODELS

logger = logging.getLogger(__name__)


async def cleanup_images(limit=50):
    cloud = CloudinaryImages()
    removed = 0
    for _ in range(limit):
        async with get_db_session() as session:
            ticket = await session.scalar(select(ImageCleanup).where(
                ImageCleanup.available_at <= datetime.now(timezone.utc),
                ImageCleanup.cloud_name == cloud.cloud_name,
            ).order_by(ImageCleanup.available_at).limit(1).with_for_update(skip_locked=True))
            if ticket is None:
                break
            # Bảo vệ mọi tài sản đang được gắn, kể cả ảnh chụp lịch sử không còn hoạt động.
            attached = False
            for model in MODELS.values():
                if await session.scalar(select(model.id).where(model.image_public_id == ticket.public_id).limit(1)):
                    attached = True
                    break
            if attached:
                await session.delete(ticket)
                continue
            try:
                await cloud.destroy(ticket.public_id)
            except Exception:
                ticket.available_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                logger.warning("Cloudinary cleanup deferred for public_id=%s", ticket.public_id)
            else:
                await session.delete(ticket)
                removed += 1
    return removed


async def main():
    try:
        print(f"Removed {await cleanup_images()} unused images")
    finally:
        await close_crud_db_pool()


async def cleanup_loop():
    """Mỗi worker API đều có thể chạy hàm này; SKIP LOCKED phân phối việc dọn dẹp an toàn."""
    while True:
        try:
            await cleanup_images()
        except Exception:
            logger.warning("Image cleanup unavailable; retrying in five minutes")
        await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())
