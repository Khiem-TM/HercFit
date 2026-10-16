"""LangGraph persistence using the shared PostgreSQL configuration."""

from contextlib import asynccontextmanager

# Re-export helpers to preserve existing imports from memory.postgres.
from core.database import get_postgres_connection_string, validate_postgres_config
from core.llm import get_embeddings
from core.settings import settings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def _memory_pool(component: str):
    validate_postgres_config()
    async with AsyncConnectionPool(
        get_postgres_connection_string(),
        min_size=settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
        max_size=settings.POSTGRES_MAX_CONNECTIONS_PER_POOL,
        timeout=settings.POSTGRES_POOL_TIMEOUT,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "application_name": f"{settings.POSTGRES_APPLICATION_NAME}-{component}",
        },
        check=AsyncConnectionPool.check_connection,
        open=False,
    ) as pool:
        await pool.wait(timeout=settings.POSTGRES_POOL_TIMEOUT)
        yield pool


@asynccontextmanager
async def get_postgres_saver():
    async with _memory_pool("saver") as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        yield checkpointer


@asynccontextmanager
async def get_postgres_store():
    index = None
    if settings.EMBEDDING_MODEL:
        index = {"dims": settings.EMBEDDING_DIMENSIONS, "embed": get_embeddings()}
    async with _memory_pool("store") as pool:
        store = AsyncPostgresStore(pool, index=index)
        await store.setup()
        yield store
