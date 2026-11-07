"""Client embedding của worker: thử lại có giới hạn, vector đơn vị, mặc định vai trò E5 'passage'."""

import asyncio
import math

import httpx

from agentic.embedding.core import EmbeddingClient

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class FPTEmbeddingClient(EmbeddingClient):
    async def embed(self, texts, *, input_type="passage"):
        if not self.settings.EMBEDDING_API_KEY:
            raise ValueError("Set FPT_API_KEY or EMBEDDING_API_KEY in the environment")
        retries = self.settings.KNOWLEDGE_EMBEDDING_RETRIES
        for attempt in range(retries):
            try:
                vectors = await super().embed(texts, input_type=input_type)
                # Truy hồi dùng tìm kiếm cosine. Lưu vector đã chuẩn hoá một cách nhất quán.
                return [[x / math.hypot(*vector) for x in vector] for vector in vectors]
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                status = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                if (
                    status is not None and status not in RETRYABLE_STATUS
                ) or attempt + 1 == retries:
                    raise
                await asyncio.sleep(retry_delay(exc, attempt))
        raise RuntimeError("Unreachable")


def retry_delay(exc, attempt):
    """Backoff luỹ thừa, theo Retry-After khi nhà cung cấp gửi; tối đa 30 giây."""
    delay = 2**attempt
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            delay = float(exc.response.headers.get("Retry-After", delay))
        except ValueError:
            pass
    return min(30, max(0, delay))
