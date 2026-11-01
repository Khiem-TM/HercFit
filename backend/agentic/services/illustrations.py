"""Ảnh minh hoạ cho thực phẩm/bài tập đã tra cứu (chỉ để hiển thị, không bao giờ là bằng chứng dinh dưỡng)."""
import asyncio
import logging

logger = logging.getLogger(__name__)
# Tên món ăn đơn giản cho kết quả tốt nhất; tên bài tập thường là thuật ngữ gym tiếng Anh.
SUFFIX = {'exercises': 'exercise'}


async def find_illustrations(tavily, queries, domain: str | None, limit: int = 4, *, reserve=None) -> list[dict]:
    """Tiêu tối đa hai giây tổng cộng; ảnh lỗi không bao giờ làm bỏ bằng chứng văn bản."""
    try:
        async with asyncio.timeout(2):
            return await _find_illustrations(tavily, queries, domain, limit, reserve)
    except TimeoutError:
        logger.info('illustration_search_timeout')
        return []


async def _find_illustrations(tavily, queries, domain, limit, reserve):
    seen = set()
    for query in [queries] if isinstance(queries, str) else queries:
        text = f"{query or ''} {SUFFIX.get(domain, '')}".strip()
        if not query or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        try:
            images = await tavily.search_images(text, limit=limit, **({'reserve': reserve} if reserve else {}))
        except Exception as exc:
            logger.warning('illustration_search_failed error_type=%s', type(exc).__name__)
            continue
        if images:
            return images
    return []
