from contextlib import asynccontextmanager
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agentic.memory.store import Store
from agentic.migrations.runner import migrate_pool

@asynccontextmanager
async def persistence(settings):
    async with AsyncConnectionPool(settings.AGENT_DATABASE_URL.get_secret_value(), min_size=1,
                                   max_size=getattr(settings,'AGENT_DATABASE_POOL_SIZE',10),
                                   open=False, kwargs={'autocommit': True, 'row_factory': dict_row}) as pool, \
               AsyncConnectionPool(settings.AGENT_DATABASE_URL.get_secret_value(), min_size=1,
                                   max_size=getattr(settings,'AGENT_SESSION_POOL_SIZE',10),
                                   open=False, kwargs={'autocommit': True, 'row_factory': dict_row}) as locks:
        await pool.open(wait=True)
        await locks.open(wait=True)
        store = Store(pool, lock_pool=locks)
        saver = AsyncPostgresSaver(pool)
        try:
            await store.ready()
            async with pool.connection() as conn:
                await conn.execute('SELECT 1 FROM checkpoint_migrations LIMIT 1')
        except Exception:
            if getattr(settings, 'MODE', 'dev') == 'dev':
                await migrate_pool(pool, saver)
                await store.ready()
            else:
                raise
        yield store, saver
