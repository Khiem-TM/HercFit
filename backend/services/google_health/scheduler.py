"""Periodic Google Health synchronization inside each API worker.

Every worker may run the loop: leases with SKIP LOCKED hand each due connection
to exactly one worker. Run once from a shell with `python -m services.google_health`.
"""
import asyncio
import logging

from services.google_health.sync import sync_connection

logger = logging.getLogger(__name__)
POLL_SECONDS = 60
MAX_PER_TICK = 20


async def sync_due(limit: int = MAX_PER_TICK) -> int:
    synced = 0
    for _ in range(limit):
        result = await sync_connection()
        if result.get("status") == "idle":
            break
        synced += 1
    return synced


async def health_sync_loop() -> None:
    while True:
        try:
            await sync_due()
        except Exception as exc:
            logger.warning("google_health_sync_loop_error error=%s", type(exc).__name__)
        await asyncio.sleep(POLL_SECONDS)
