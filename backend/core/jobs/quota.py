"""Token bucket trong PostgreSQL, dùng chung cho mọi tiến trình worker.

`take(key, rate_per_minute)` tiêu một token hoặc trả về số giây phải chờ.
Các bucket: `gh:user:{connection}` (mặc định theo tài liệu của Google là 300 request mỗi
phút mỗi người dùng) và `gh:project` (quota của project, lấy từ cấu hình).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from core.database import get_db_session


async def take(key: str, per_minute: int, *, capacity: int | None = None) -> float:
    """0 khi đã tiêu được một token, ngược lại là số giây cho tới khi có token."""
    rate = per_minute / 60.0
    capacity = capacity or per_minute
    async with get_db_session() as session:
        row = (await session.execute(text("""
            INSERT INTO rate_buckets AS b (key, tokens, refilled_at) VALUES (:key, :capacity - 1, now())
            ON CONFLICT (key) DO UPDATE SET
                tokens = LEAST(:capacity, b.tokens + EXTRACT(EPOCH FROM now() - b.refilled_at) * :rate) - 1,
                refilled_at = now()
            WHERE LEAST(:capacity, b.tokens + EXTRACT(EPOCH FROM now() - b.refilled_at) * :rate) >= 1
            RETURNING tokens"""), {"key": key, "capacity": capacity, "rate": rate})).first()
        if row is not None:
            return 0.0
        tokens = (await session.execute(text(
            "SELECT LEAST(:capacity, tokens + EXTRACT(EPOCH FROM now() - refilled_at) * :rate) FROM rate_buckets "
            "WHERE key = :key"), {"key": key, "capacity": capacity, "rate": rate})).scalar_one()
    return max(0.05, (1 - float(tokens)) / rate)


async def acquire(keys: list[tuple[str, int]], *, max_wait: float = 30.0, sleep=asyncio.sleep) -> None:
    """Chờ (có giới hạn) một token ở mọi bucket; ném TimeoutError khi quota vẫn cạn."""
    waited = 0.0
    for key, per_minute in keys:
        while True:
            wait = await take(key, per_minute)
            if wait == 0:
                break
            if waited + wait > max_wait:
                raise TimeoutError(key)
            await sleep(wait)
            waited += wait
