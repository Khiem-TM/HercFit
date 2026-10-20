"""Long-term memory and RAG retrieval backed by PostgreSQL pgvector (AsyncPostgresStore) or in-memory fallback."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from config.settings import agent_settings
from core.exceptions import MemoryStoreError
from core.llm import get_embeddings


class LongTermMemory:
    """Manages cross-session semantic memory and user knowledge retrieval (RAG)."""

    def __init__(self) -> None:
        self._in_memory_records: dict[str, list[dict[str, Any]]] = {}

    async def store_fact(
        self,
        user_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a long-term user fact or fitness preference."""
        if not user_id or not content.strip():
            raise MemoryStoreError("user_id and non-empty content are required to store memory.")
        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "content": content.strip(),
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._in_memory_records.setdefault(user_id, []).append(record)
        return record

    async def retrieve_relevant(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant long-term memory facts for a user."""
        records = self._in_memory_records.get(user_id, [])
        if not query.strip():
            return records[-limit:]
        q_lower = query.lower()
        scored = sorted(
            records,
            key=lambda r: (q_lower in r["content"].lower(), r["created_at"]),
            reverse=True,
        )
        return scored[:limit]

    @asynccontextmanager
    async def postgres_store_context(self):
        """Yield an AsyncPostgresStore with optional pgvector embedding index."""
        from langgraph.store.postgres import AsyncPostgresStore
        from psycopg.conninfo import make_conninfo
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        conninfo = make_conninfo(
            user=agent_settings.POSTGRES_USER,
            password=agent_settings.POSTGRES_PASSWORD.get_secret_value(),
            host=agent_settings.POSTGRES_HOST,
            port=agent_settings.POSTGRES_PORT,
            dbname=agent_settings.POSTGRES_DB,
            connect_timeout=agent_settings.POSTGRES_CONNECT_TIMEOUT,
        )
        index = None
        if agent_settings.EMBEDDING_MODEL:
            index = {
                "dims": agent_settings.EMBEDDING_DIMENSIONS,
                "embed": get_embeddings(),
            }
        async with AsyncConnectionPool(
            conninfo,
            min_size=agent_settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
            max_size=agent_settings.POSTGRES_MAX_CONNECTIONS_PER_POOL,
            timeout=agent_settings.POSTGRES_POOL_TIMEOUT,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "application_name": f"{agent_settings.POSTGRES_APPLICATION_NAME}-store",
            },
            check=AsyncConnectionPool.check_connection,
            open=False,
        ) as pool:
            await pool.wait(timeout=agent_settings.POSTGRES_POOL_TIMEOUT)
            if agent_settings.PGVECTOR_ENABLED:
                async with pool.connection() as conn:
                    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            store = AsyncPostgresStore(pool, index=index)
            await store.setup()
            yield store

