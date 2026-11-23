"""Pool kết nối và checkpointer LangGraph của agent; khôi phục phép chiếu từ các checkpoint đã commit."""

import logging
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agentic.configs.settings import AgentSettings
from agentic.memory.store import Store
from agentic.migrations.runner import migrate_pool


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


# --------------------------------------------------------------------------------------------------
# Khôi phục quan sát của phép chiếu trực tiếp từ các checkpoint LangGraph đã commit.
# --------------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)


async def reconcile_checkpoints(pool, limit=50, grace_seconds=180):
    store, saver = Store(pool), AsyncPostgresSaver(pool)
    count = 0
    for row in await store.reconciliation_threads(limit, grace_seconds):
        try:
            checkpoint = await saver.aget_tuple({"configurable": {"thread_id": row["thread_id"]}})
            if checkpoint and checkpoint.checkpoint["id"] != row["kg_checkpoint_id"]:
                await store.archive_snapshot(checkpoint.checkpoint["channel_values"])
                await store.record_execution_state(
                    checkpoint.checkpoint["channel_values"], checkpoint.checkpoint["id"]
                )
                count += 1
            await store.checked_thread(row["thread_id"])
        except Exception as exc:
            logger.warning("kg_checkpoint_reconcile_failed error_type=%s", type(exc).__name__)
    return count
