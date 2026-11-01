"""Transactional domain events (outbox): business facts other parts react to.

`publish` inserts in the caller's transaction, so an event exists exactly when
the change that caused it committed. Consumers (workers, the agent service)
claim undelivered events with `pending` and acknowledge them with `delivered`;
each consumer keeps its own delivery rows, so a slow consumer never blocks
another, and events committed out of id order are still seen.

Payloads carry identifiers and decisions only, never health values.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TOPICS = frozenset({
    "consent.changed",          # {purpose, data_group, granted, version}
    "health.connection.changed",  # {status, generation}
    "health.records.changed",   # {data_types, start, end}
})


async def publish(session: AsyncSession, topic: str, user_id: UUID | None, payload: dict[str, Any] | None = None) -> int:
    if topic not in TOPICS:
        raise ValueError(f"Unknown domain event topic {topic!r}")
    return (await session.execute(text(
        "INSERT INTO domain_events (topic, user_id, payload) VALUES (:topic, :user_id, CAST(:payload AS jsonb)) "
        "RETURNING id"), {"topic": topic, "user_id": user_id, "payload": json.dumps(payload or {})})).scalar_one()


async def pending(session: AsyncSession, consumer: str, topics: tuple[str, ...], *, limit: int = 100,
                  lookback_days: int = 7) -> list[dict[str, Any]]:
    """Undelivered events for this consumer, oldest first, locked against concurrent consumers."""
    rows = await session.execute(text("""
        SELECT e.id, e.topic, e.user_id, e.payload, e.occurred_at FROM domain_events e
        WHERE e.topic = ANY(:topics) AND e.occurred_at > now() - make_interval(days => :days)
          AND NOT EXISTS (SELECT 1 FROM domain_event_deliveries d WHERE d.consumer = :consumer AND d.event_id = e.id)
        ORDER BY e.id LIMIT :limit FOR UPDATE OF e SKIP LOCKED"""),
        {"topics": list(topics), "consumer": consumer, "limit": limit, "days": lookback_days})
    return [dict(row._mapping) for row in rows]


async def delivered(session: AsyncSession, consumer: str, event_id: int) -> None:
    await session.execute(text(
        "INSERT INTO domain_event_deliveries (consumer, event_id) VALUES (:consumer, :event_id) "
        "ON CONFLICT DO NOTHING"), {"consumer": consumer, "event_id": event_id})
