"""Forget health data the assistant already holds when the user revokes consent.

The backend publishes `consent.changed` in the same transaction as the decision
(domain_events). This consumer, running inside the agent service, handles each
revocation once (domain_event_deliveries):

* each conversation's current checkpoint drops health tool outputs and the
  context card, so nothing is carried into the next turn;
* superseded per-turn checkpoints (raw tool outputs of older turns) are deleted;
* the Redis session memory (summaries, recalled turns) is forgotten; it is
  rebuilt from the remaining checkpoints;
* conversation episodes about health (graph `Run`/`Execution` nodes: health
  domain, a health tool, or a reference to a device record) are tombstoned in
  the graph and their journal rows deleted, so a graph rebuild cannot restore
  them. Episodes never hold measured values, but they do reveal what was asked.

Device facts in the graph are already tombstoned by the backend trigger. The
visible chat transcript stays: it is the user's conversation, which they can clear.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from agentic.tools.registry import REGISTRY

logger = logging.getLogger(__name__)
CONSUMER = 'agentic.consent_purge'
POLL_SECONDS = 10
HEALTH_TOOLS = frozenset(name for name, spec in REGISTRY.items() if spec.domain == 'health')
HEALTH_DOMAINS = frozenset({'health'})
HEALTH_RECORD_KINDS = frozenset({'DailyHealth', 'SleepSession', 'DeviceWorkout'})


def is_health_episode(data: dict) -> bool:
    """A journaled turn (`tools`) or execution (`tool`) that touched health data."""
    tools = [data['tool']] if data.get('tool') else list(data.get('tools') or [])
    refs = data.get('resource_refs') or []
    return (data.get('domain') in HEALTH_DOMAINS or any(tool in HEALTH_TOOLS for tool in tools)
            or any(isinstance(ref, dict) and ref.get('kind') in HEALTH_RECORD_KINDS for ref in refs))


async def purge_user_health(runtime, user_id: str) -> dict:
    sessions = threads_deleted = rewritten = 0
    for session_id in await runtime.store.user_session_ids(user_id):
        sessions += 1
        async with runtime.store.session(session_id, user_id, create=False) as session:
            current = session.get('thread_id')
            for thread in await runtime.store.threads(session_id):
                if thread != current:
                    await runtime.saver.adelete_thread(thread)
                    await runtime.store.forget_thread(thread)
                    threads_deleted += 1
            if current:
                snapshot = await runtime.state(current)
                values = (snapshot.values if snapshot else None) or {}
                outputs = values.get('tool_outputs') or []
                kept = [output for output in outputs if output.get('tool') not in HEALTH_TOOLS]
                # A pending confirmation keeps its thread untouched; its outputs are not health reads.
                if (len(kept) != len(outputs) or values.get('user_context')) and not values.get('pending_action'):
                    await runtime.graph.aupdate_state(runtime.config(current),
                                                      {'tool_outputs': kept, 'user_context': None},
                                                      as_node='__start__')
                    rewritten += 1
        if runtime.memory:
            await runtime.memory.forget(session_id)
    episodes = await runtime.store.forget_episodes(user_id, is_health_episode)
    return {'sessions': sessions, 'threads_deleted': threads_deleted, 'checkpoints_rewritten': rewritten,
            'episodes_removed': sum(episodes.values())}


async def purge_once(runtime, *, limit: int = 50) -> int:
    """Handle undelivered consent events; revocations purge, grants are only acknowledged."""
    handled = 0
    async with runtime.store.pool.connection() as conn:
        async with conn.transaction():
            rows = await (await conn.execute('''
                SELECT e.id, e.user_id, e.payload FROM domain_events e
                WHERE e.topic = 'consent.changed' AND e.occurred_at > now() - interval '7 days'
                  AND NOT EXISTS (SELECT 1 FROM domain_event_deliveries d WHERE d.consumer = %s AND d.event_id = e.id)
                ORDER BY e.id LIMIT %s FOR UPDATE OF e SKIP LOCKED''', (CONSUMER, limit))).fetchall()
            for row in rows:
                payload = row['payload'] or {}
                if payload.get('purpose') == 'assistant' and not payload.get('granted'):
                    result = await purge_user_health(runtime, str(row['user_id']))
                    logger.info('consent_purge sessions=%s threads=%s rewritten=%s episodes=%s', result['sessions'],
                                result['threads_deleted'], result['checkpoints_rewritten'], result['episodes_removed'])
                await conn.execute('INSERT INTO domain_event_deliveries (consumer, event_id) VALUES (%s, %s) '
                                   'ON CONFLICT DO NOTHING', (CONSUMER, row['id']))
                handled += 1
    return handled


async def purge_forever(runtime) -> None:
    while True:
        with suppress(Exception):
            await purge_once(runtime)
        await asyncio.sleep(POLL_SECONDS)
