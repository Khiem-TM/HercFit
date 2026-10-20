"""Checkpoint and persistent state management for LangGraph (In-Memory, PostgreSQL, Redis)."""

from contextlib import asynccontextmanager
import logging
from typing import Any

from config.settings import CheckpointBackend, agent_settings

try:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:

    class BaseCheckpointSaver:  # type: ignore[no-redef]
        pass

    class MemorySaver(BaseCheckpointSaver):  # type: ignore[no-redef]
        def __init__(self) -> None:
            self.storage: dict[str, dict[str, Any]] = {}


logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages lifecycle of LangGraph state checkpointers across Memory, Postgres, and Redis."""

    def __init__(self, backend: CheckpointBackend | str | None = None) -> None:
        self.backend = CheckpointBackend(
            backend or agent_settings.CHECKPOINT_BACKEND
        )
        self._memory_saver = MemorySaver()

    def get_memory_saver(self) -> MemorySaver:
        return self._memory_saver

    @staticmethod
    def build_postgres_conninfo() -> str:
        from psycopg.conninfo import make_conninfo

        return make_conninfo(
            user=agent_settings.POSTGRES_USER,
            password=agent_settings.POSTGRES_PASSWORD.get_secret_value(),
            host=agent_settings.POSTGRES_HOST,
            port=agent_settings.POSTGRES_PORT,
            dbname=agent_settings.POSTGRES_DB,
            connect_timeout=agent_settings.POSTGRES_CONNECT_TIMEOUT,
        )

    @asynccontextmanager
    async def lifespan_saver(self):
        """Yield the configured checkpointer (MemorySaver or AsyncPostgresSaver)."""
        if self.backend == CheckpointBackend.POSTGRES:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                from psycopg.rows import dict_row
                from psycopg_pool import AsyncConnectionPool

                async with AsyncConnectionPool(
                    self.build_postgres_conninfo(),
                    min_size=agent_settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
                    max_size=agent_settings.POSTGRES_MAX_CONNECTIONS_PER_POOL,
                    timeout=agent_settings.POSTGRES_POOL_TIMEOUT,
                    kwargs={
                        "autocommit": True,
                        "row_factory": dict_row,
                        "application_name": f"{agent_settings.POSTGRES_APPLICATION_NAME}-saver",
                    },
                    check=AsyncConnectionPool.check_connection,
                    open=False,
                ) as pool:
                    await pool.wait(timeout=agent_settings.POSTGRES_POOL_TIMEOUT)
                    saver = AsyncPostgresSaver(pool)
                    await saver.setup()
                    yield saver
                    return
            except Exception as exc:
                logger.warning(
                    "Falling back to MemorySaver because Postgres checkpointer failed: %s",
                    exc,
                )

        yield self._memory_saver

    def get_default_saver(self) -> Any:
        return self._memory_saver

