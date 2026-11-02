"""Wake the exporter in the same transaction as an outbox write.

Each producer event has its own durable wakeup, so a concurrently finishing
dispatcher cannot swallow it. Queue claiming serializes dispatch per connection.
"""
from core.jobs import queue


async def enqueue(session, connection, *, event_id, operation_id=None):
    return await queue.enqueue(
        session, "GH_EXPORT_DISPATCH", queue="export", user_id=connection.user_id,
        connection_id=connection.id, connection_generation=connection.generation,
        dedupe_key=f"export-event:{event_id}", operation_id=operation_id, priority=95)
