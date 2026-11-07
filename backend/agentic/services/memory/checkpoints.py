from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agentic.core.app.config import AgentSettings
from agentic.migrations.runner import migrate_pool
from agentic.services.memory.store import Store


@asynccontextmanager
async def persistence(settings: AgentSettings):
    # Một pool: lease của cuộc trò chuyện không còn ghim một kết nối suốt cả lượt chạy.
    async with AsyncConnectionPool(
        settings.AGENT_DATABASE_URL.get_secret_value(),
        min_size=1,
        max_size=settings.AGENT_DATABASE_POOL_SIZE,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    ) as pool:
        await pool.open(wait=True)
        store = Store(
            pool,
            lease_seconds=settings.session_lease_seconds,
            wait_seconds=settings.SESSION_LEASE_WAIT_SECONDS,
        )
        saver = AsyncPostgresSaver(pool)
        try:
            await store.ready()
            async with pool.connection() as conn:
                await conn.execute("SELECT 1 FROM checkpoint_migrations LIMIT 1")
        except Exception:
            if settings.MODE == "dev":
                await migrate_pool(pool, saver)
                await store.ready()
            else:
                raise
        yield store, saver
