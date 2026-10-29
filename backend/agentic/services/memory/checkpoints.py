from contextlib import asynccontextmanager
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agentic.services.memory.store import Store
from agentic.migrations.runner import migrate_pool

@asynccontextmanager
async def persistence(settings):
    # One pool: conversation leases no longer pin a connection for the duration of a run.
    async with AsyncConnectionPool(settings.AGENT_DATABASE_URL.get_secret_value(), min_size=1,
                                   max_size=getattr(settings,'AGENT_DATABASE_POOL_SIZE',10),
                                   open=False, kwargs={'autocommit': True, 'row_factory': dict_row}) as pool:
        await pool.open(wait=True)
        store = Store(pool, lease_seconds=getattr(settings, 'session_lease_seconds', 180),
                      wait_seconds=getattr(settings, 'SESSION_LEASE_WAIT_SECONDS', 30))
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
