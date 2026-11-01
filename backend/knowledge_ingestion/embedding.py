"""Adapter FPT API với số lần thử lại có giới hạn, vector đơn vị và vai trò đầu vào E5 tường minh."""
import asyncio
import math

import httpx

from embedding.client import EmbeddingClient


class FPTEmbeddingClient(EmbeddingClient):
    async def embed(self, texts, *, input_type='passage'):
        if not self.settings.EMBEDDING_API_KEY:
            raise ValueError('Set FPT_API_KEY or EMBEDDING_API_KEY in the environment')
        for attempt in range(self.settings.KNOWLEDGE_EMBEDDING_RETRIES):
            try:
                vectors = await super().embed(texts, input_type=input_type)
                # Truy hồi dùng tìm kiếm cosine. Lưu vector đã chuẩn hoá một cách nhất quán.
                return [[x / math.hypot(*vector) for x in vector] for vector in vectors]
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {408, 429, 500, 502, 503, 504}
                if not retryable or attempt + 1 == self.settings.KNOWLEDGE_EMBEDDING_RETRIES:
                    raise
                delay = 2 ** attempt
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        delay = float(exc.response.headers.get('Retry-After', delay))
                    except ValueError:
                        pass
                await asyncio.sleep(min(30, max(0, delay)))
        raise RuntimeError('Unreachable')
