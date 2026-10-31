"""Shared PostgreSQL configuration, SQLAlchemy 2.0 Async ORM, and connection lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.settings import settings
from core.transaction import transaction

_crud_pool: AsyncConnectionPool | None = None
_async_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy 2.0 ORM models."""


def get_postgres_connection_string() -> str:
    """Let libpq escape credentials, including passwords containing URI characters."""
    return make_conninfo(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD.get_secret_value() if settings.POSTGRES_PASSWORD else None,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        dbname=settings.POSTGRES_DB,
        connect_timeout=settings.POSTGRES_CONNECT_TIMEOUT,
    )


def get_sqlalchemy_url() -> URL:
    """Build SQLAlchemy URL using psycopg v3 dialect."""
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD.get_secret_value() if settings.POSTGRES_PASSWORD else None,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
    )


def get_async_engine() -> AsyncEngine:
    """Lazily initialize and return the shared SQLAlchemy AsyncEngine."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(
            get_sqlalchemy_url(),
            pool_pre_ping=True,
            pool_size=settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
            max_overflow=max(
                0,
                settings.POSTGRES_MAX_CONNECTIONS_PER_POOL
                - settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
            ),
            pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
        )
    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared async_sessionmaker bound to the AsyncEngine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def init_crud_db_pool() -> None:
    """Wait for PostgreSQL readiness before serving requests."""
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
    except BaseException:
        await pool.close()
        raise
    _crud_pool = pool


async def close_crud_db_pool() -> None:
    """Close and reset the pool and SQLAlchemy engine on shutdown."""
    global _crud_pool, _async_engine, _session_factory
    if _crud_pool is not None:
        await _crud_pool.close()
        _crud_pool = None
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _session_factory = None


@asynccontextmanager
async def get_db_connection() -> AsyncIterator[AsyncConnection]:
    """Commit on success, roll back on error; never silently fall back to mock data."""
    if _crud_pool is None:
        raise RuntimeError("Database pool is not initialized; call init_crud_db_pool() at startup")
    async with _crud_pool.connection() as conn:
        yield conn


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Context manager yielding a transactional SQLAlchemy AsyncSession (for services/tools)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a SQLAlchemy AsyncSession."""
    async with get_db_session() as session:
        yield session


# The trace GUC is read only by outbox/job inserts, so it is set once per
# transaction on write paths (ORM flushes and DML statements), never on reads.
from sqlalchemy import event, text as sql_text
from sqlalchemy.orm import Session


def attach_trace_context(session):
    connection = session.connection()  # begins the transaction when a statement opens it
    transaction = session.get_transaction()
    if session.info.get('trace_transaction') is transaction or connection.dialect.name != 'postgresql':
        return
    from agentic.observability import durable_context
    import json
    session.info['trace_transaction'] = transaction
    context = durable_context()
    if context:
        connection.execute(sql_text("SELECT set_config('hercfit.trace_context', :context, true)"), {'context': json.dumps(context)})


@event.listens_for(Session, 'before_flush')
def trace_flush(session, flush_context, instances):
    attach_trace_context(session)


@event.listens_for(Session, 'do_orm_execute')
def trace_statement(orm_execute_state):
    if orm_execute_state.is_insert or orm_execute_state.is_update or orm_execute_state.is_delete:
        attach_trace_context(orm_execute_state.session)
