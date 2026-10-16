"""Shared PostgreSQL configuration and transactional CRUD connection lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core.settings import settings

_crud_pool: AsyncConnectionPool | None = None


def validate_postgres_config() -> None:
    """Validate settings again for callers of the legacy memory helpers."""
    settings.validate_configuration()


def get_postgres_connection_string() -> str:
    """Let libpq escape credentials, including passwords containing URI characters."""
    return make_conninfo(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD.get_secret_value(),
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        connect_timeout=settings.POSTGRES_CONNECT_TIMEOUT,
    )


async def init_crud_db_pool() -> None:
    """Wait for PostgreSQL readiness and prepare pgvector before serving requests."""
    global _crud_pool
    if _crud_pool is not None:
        return
    pool = AsyncConnectionPool(
        get_postgres_connection_string(),
        min_size=settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
        max_size=settings.POSTGRES_MAX_CONNECTIONS_PER_POOL,
        timeout=settings.POSTGRES_POOL_TIMEOUT,
        kwargs={
            "autocommit": False,
            "row_factory": dict_row,
            "application_name": f"{settings.POSTGRES_APPLICATION_NAME}-crud",
        },
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    try:
        await pool.open(wait=True, timeout=settings.POSTGRES_POOL_TIMEOUT)
        if settings.PGVECTOR_ENABLED:
            async with pool.connection() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except BaseException:
        await pool.close()
        raise
    _crud_pool = pool


async def close_crud_db_pool() -> None:
    """Close and reset the pool on shutdown."""
    global _crud_pool
    if _crud_pool is not None:
        await _crud_pool.close()
        _crud_pool = None


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[AsyncConnection]:
    """Commit on success, roll back on error; never silently fall back to mock data."""
    if _crud_pool is None:
        raise RuntimeError("Database pool is not initialized; call init_crud_db_pool() at startup")
    async with _crud_pool.connection() as conn:
        yield conn


async def get_db() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency using the shared PostgreSQL pool."""
    async with get_db_connection() as conn:
        yield conn
