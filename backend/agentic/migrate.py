"""Run once before deployment: python -m agentic.migrate (from backend/)."""
import asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agentic.config.settings import agent_settings
from agentic.migrations.runner import migrate_pool

async def migrate():
    async with AsyncConnectionPool(agent_settings.AGENT_DATABASE_URL.get_secret_value(), open=False,
                                   kwargs={'autocommit': True, 'row_factory': dict_row}) as pool:
        await pool.open(wait=True)
        await migrate_pool(pool, AsyncPostgresSaver(pool))

if __name__ == '__main__':
    asyncio.run(migrate())
