"""PostgreSQL persistence for LangGraph checkpoints and long-term memory."""

from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

from agents.memory.postgres import get_postgres_saver, get_postgres_store


def initialize_database() -> AbstractAsyncContextManager[AsyncPostgresSaver]:
    return get_postgres_saver()


def initialize_store() -> AbstractAsyncContextManager[AsyncPostgresStore]:
    return get_postgres_store()


__all__ = ["initialize_database", "initialize_store"]
