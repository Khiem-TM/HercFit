"""Token buckets in PostgreSQL, shared by every worker process.

`take(key, rate_per_minute)` spends one token or returns the seconds to wait.
Buckets: `gh:user:{connection}` (Google's documented default is 300 requests per
minute per user) and `gh:project` (the project's quota, from configuration).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from core.database import get_db_session


async def take(key: str, per_minute: int, *, capacity: int | None = None) -> float:
    """0 when a token was spent, else seconds until one is available."""
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
    """Wait (bounded) for a token in every bucket; raises TimeoutError when quota stays exhausted."""
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
