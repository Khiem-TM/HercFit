"""Chạy một lần trước khi triển khai: python -m agentic.scripts.migrate (từ backend/)."""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agentic.core.app.config import agent_settings
from agentic.migrations.runner import migrate_pool


async def migrate():
    async with AsyncConnectionPool(
        agent_settings.AGENT_DATABASE_URL.get_secret_value(),
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    ) as pool:
        await pool.open(wait=True)
        await migrate_pool(pool, AsyncPostgresSaver(pool))


if __name__ == "__main__":
    asyncio.run(migrate())
