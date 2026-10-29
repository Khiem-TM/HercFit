"""Recover projection observations directly from committed LangGraph checkpoints."""
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agentic.services.memory.store import Store

logger = logging.getLogger(__name__)


async def reconcile_checkpoints(pool, limit=50, grace_seconds=180):
    store, saver = Store(pool), AsyncPostgresSaver(pool)
    count = 0
    for row in await store.reconciliation_threads(limit, grace_seconds):
        try:
            checkpoint = await saver.aget_tuple({'configurable':{'thread_id':row['thread_id']}})
            if checkpoint and checkpoint.checkpoint['id'] != row['kg_checkpoint_id']:
                await store.record_execution_state(checkpoint.checkpoint['channel_values'], checkpoint.checkpoint['id'])
                count += 1
            await store.checked_thread(row['thread_id'])
        except Exception as exc:
            logger.warning('kg_checkpoint_reconcile_failed error_type=%s', type(exc).__name__)
    return count
