"""Redis session memory: a rebuildable hot tier over PostgreSQL checkpoints.

Checkpoints stay authoritative for approvals, recovery and the verbatim
window. Redis keeps each session's full transcript, a rolling summary of the
turns that left the window and the records the conversation touched.
Request-path calls run inside the session's advisory lock, are bounded by
REDIS_TIMEOUT_MS and never raise: an outage only loses the extra memory.
"""
from agentic.prompts.registry import get_prompt
import asyncio
import contextvars
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import monotonic, perf_counter
from typing import NamedTuple
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from redis.asyncio import Redis
from redis.exceptions import WatchError

from agentic.observability import annotate, graph_config, observed
from agentic.services.memory.transcript import (LAST_MESSAGE_CHARS, TITLE_CHARS, entities_from_state, fold_plan, gap_turns,
                                       merge_entities, outside_messages, render_memory, seed_turns, turn_from_state)

SUMMARY_PROMPT = get_prompt('memory.summary')

logger = logging.getLogger(__name__)

BREAKER_SECONDS = 5
SUMMARY_LOCK_MS = 120_000
FOLD_TURNS = 20
FOLD_CHARS = 12_000
FOLD_ROUNDS = 5
MEMORY_CHARS = 8_000


def _now():
    return datetime.now(timezone.utc).isoformat()


class Keys(NamedTuple):
    meta: str
    turns: str
    order: str
    summary: str
    entities: str
    lock: str

    @property
    def data(self):
        return (self.meta, self.turns, self.order, self.summary, self.entities)


@dataclass
class Recall:
    summary: str | None = None
    upto_seq: int = 0
    covered: int = 0
    gap: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    message_count: int = 0
    status: str = 'empty'

    @classmethod
    def from_state(cls, value, status):
        value = value if isinstance(value, dict) else {}
        return cls(summary=value.get('summary'), upto_seq=int(value.get('upto_seq') or 0),
                   covered=int(value.get('covered') or 0), entities=list(value.get('entities') or []), status=status)

    def render(self):
        return render_memory(self.summary, self.gap, self.entities, MEMORY_CHARS) or None

    def state(self):
        # Durable copy in the checkpoint: losing Redis cannot lose the summary.
        return {'summary': self.summary, 'upto_seq': self.upto_seq, 'covered': self.covered, 'entities': self.entities}


class SessionMemory:
    def __init__(self, redis, settings, models=None):
        self.redis, self.settings, self.models = redis, settings, models
        self.mode = getattr(settings, 'SESSION_MEMORY_MODE', 'off')
        self.prefix = getattr(settings, 'REDIS_KEY_PREFIX', 'hf:agent')
        self.timeout = getattr(settings, 'REDIS_TIMEOUT_MS', 100) / 1000
        self.ttl = getattr(settings, 'SESSION_MEMORY_TTL_SECONDS', 30 * 24 * 3600)
        self.max_turns = getattr(settings, 'SESSION_MEMORY_MAX_TURNS', 200)
        self.window = getattr(settings, 'SESSION_MEMORY_WINDOW_MESSAGES', 40)
        self.summarize = models is not None and getattr(settings, 'SESSION_MEMORY_SUMMARY_ENABLED', True)
        self.trigger = getattr(settings, 'SESSION_MEMORY_SUMMARY_TRIGGER_TURNS', 4)
        self.summary_chars = getattr(settings, 'SESSION_MEMORY_SUMMARY_MAX_CHARS', 2000)
        self.entity_limit = getattr(settings, 'SESSION_MEMORY_ENTITY_LIMIT', 20)
        self._down_until = 0.0
        self._purged_since = None
        self._tasks = {}

    @classmethod
    def connect(cls, settings, models=None):
        redis = Redis.from_url(settings.REDIS_URL.get_secret_value(), decode_responses=True, socket_timeout=2,
                               socket_connect_timeout=1, health_check_interval=30, max_connections=50)
        return cls(redis, settings, models)

    @property
    def reads(self):
        """Shadow mode writes and measures; only 'on' serves reads and prompts from Redis."""
        return self.mode == 'on'

    def _keys(self, session_id):
        # The hash tag keeps a session's keys in one Cluster slot for WATCH/MULTI.
        base = f'{self.prefix}:s:{{{session_id}}}'
        return Keys(base + ':meta', base + ':turns', base + ':order', base + ':summary', base + ':entities', base + ':summarizing')

    async def _guard(self, op, call, timeout=None):
        if monotonic() < self._down_until:
            return None
        try:
            async with asyncio.timeout(timeout or self.timeout):
                return await call()
        except Exception as exc:
            self._down_until = monotonic() + BREAKER_SECONDS
            # Exception text can echo keys or payloads; record the class only.
            logger.warning('session_memory_failed op=%s error_type=%s', op, type(exc).__name__)
            return None

    async def health(self):
        ok = await self._guard('ping', self.redis.ping)
        return {'mode': self.mode, 'status': 'ok' if ok else 'unavailable'}

    async def close(self):
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.redis.aclose()

    @observed('memory.record', output=False)
    async def record_run(self, values, at=None):
        """Upsert the run's turn. The caller holds the session lock."""
        values = values or {}
        if not values.get('session_id') or not values.get('user_id') or not turn_from_state(values):
            return False
        return bool(await self._guard('record', lambda: self._record(values, at)))

    async def _read(self, k):
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.hgetall(k.meta)
            pipe.hgetall(k.summary)
            pipe.get(k.entities)
            return await pipe.execute()

    async def _record(self, values, at):
        session_id, generation = values['session_id'], int(values.get('session_generation') or 1)
        turn, k = turn_from_state(values), self._keys(values['session_id'])
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.hgetall(k.meta)
            pipe.hget(k.turns, turn['run_id'])
            pipe.exists(k.turns)
            pipe.get(k.entities)
            pipe.hgetall(k.summary)
            meta, old, stored, entities, summary = await pipe.execute()
        if not meta or int(meta.get('generation', 0)) != generation or not stored:
            # New, cleared or partially evicted session: rebuild from the checkpoint window.
            return await self._seed(k, values, at)
        old = json.loads(old) if old else None
        seq = old['seq'] if old else int(meta['next_seq'])
        message_count = int(meta['message_count']) + len(turn['messages']) - (len(old['messages']) if old else 0)
        turn_count = int(meta['turn_count']) + (0 if old else 1)
        upto, covered = int(summary.get('upto_seq', 0)), int(summary.get('covered_messages', 0))
        dropped = []
        if turn_count > self.max_turns:
            ids = await self.redis.zrange(k.order, 0, turn_count - self.max_turns - 1)
            dropped = [json.loads(row) for row in await self.redis.hmget(k.turns, ids) if row] if ids else []
        # Turns trimmed before they were summarized are skipped so counts stay aligned with the window.
        lost = [t for t in dropped if t['seq'] > upto]
        if lost:
            upto, covered = max(t['seq'] for t in lost), covered + sum(len(t['messages']) for t in lost)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(k.turns, turn['run_id'], json.dumps({**turn, 'seq': seq}, ensure_ascii=False))
            pipe.zadd(k.order, {turn['run_id']: seq})
            if dropped:
                pipe.hdel(k.turns, *(t['run_id'] for t in dropped))
                pipe.zrem(k.order, *(t['run_id'] for t in dropped))
            pipe.hset(k.meta, mapping={
                'last_message': turn['messages'][-1]['content'].strip()[:LAST_MESSAGE_CHARS],
                'message_count': message_count, 'turn_count': turn_count - len(dropped),
                'next_seq': max(int(meta['next_seq']), seq + 1), 'status': turn['status'] or '',
                'last_run_id': turn['run_id'], 'last_interaction_at': at or _now()})
            pipe.set(k.entities, json.dumps(merge_entities(json.loads(entities or '[]'), entities_from_state(values), seq,
                                                           self.entity_limit), ensure_ascii=False))
            if lost:
                pipe.hset(k.summary, mapping={'upto_seq': upto, 'covered_messages': covered, 'generation': generation})
            for key in k.data:
                pipe.expire(key, self.ttl)
            await pipe.execute()
        self._maybe_summarize(session_id, generation, message_count, covered)
        return True

    async def _seed(self, k, values, at):
        generation = int(values.get('session_generation') or 1)
        turns = seed_turns(values)[-self.max_turns:]
        for seq, turn in enumerate(turns, 1):
            turn['seq'] = seq
        messages = [m for turn in turns for m in turn['messages']]
        human = next((m for m in messages if m['role'] == 'human'), None)
        restored = values.get('session_memory') or {}
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.unlink(*k.data)
            pipe.hset(k.turns, mapping={t['run_id']: json.dumps(t, ensure_ascii=False) for t in turns})
            pipe.zadd(k.order, {t['run_id']: t['seq'] for t in turns})
            pipe.hset(k.meta, mapping={
                'user_id': str(values['user_id']), 'generation': generation,
                'title': human['content'].strip()[:TITLE_CHARS] if human else '',
                'last_message': messages[-1]['content'].strip()[:LAST_MESSAGE_CHARS],
                'message_count': len(messages), 'turn_count': len(turns), 'next_seq': len(turns) + 1,
                'status': turns[-1]['status'] or '', 'last_run_id': turns[-1]['run_id'], 'last_interaction_at': at or _now()})
            pipe.set(k.entities, json.dumps(merge_entities(restored.get('entities') or [], entities_from_state(values), len(turns),
                                                           self.entity_limit), ensure_ascii=False))
            if restored.get('summary'):
                # The checkpoint's copy covers what came before this window.
                pipe.hset(k.summary, mapping={'text': restored['summary'], 'upto_seq': 0, 'covered_messages': 0,
                                              'generation': generation, 'updated_at': _now()})
            for key in k.data:
                pipe.expire(key, self.ttl)
            await pipe.execute()
        self._maybe_summarize(values['session_id'], generation, len(messages), 0)
        return True

    async def _current(self, session, values, at):
        """Meta, summary and entities after recording the latest run if Redis missed it."""
        k = self._keys(session['session_id'])
        meta, summary, entities = await self._read(k)
        if meta and int(meta.get('generation', 0)) != int(session['generation']):
            await self.redis.unlink(*k.data)
            meta, summary, entities = {}, {}, None
        if values.get('run_id') and meta.get('last_run_id') != values['run_id'] and turn_from_state(values):
            # The run ended without recording (cancelled stream, crash) or predates Redis.
            await self._record({**values, 'session_id': session['session_id'],
                                'session_generation': int(session['generation'])}, at)
            meta, summary, entities = await self._read(k)
        return k, meta, summary, entities

    @observed('memory.recall', 'retriever', output=False)
    async def recall(self, session, previous, at=None):
        """Memory beyond the checkpoint window. Falls back to the checkpoint's own copy."""
        started = perf_counter()
        previous = previous or {}
        recall = (await self._guard('recall', lambda: self._recall(session, previous, at))
                  or Recall.from_state(previous.get('session_memory'), 'unavailable'))
        annotate(status=recall.status, duration_ms=round((perf_counter() - started) * 1000, 3), memory_mode=self.mode,
                 memory_summary_chars=len(recall.summary or ''), memory_entity_count=len(recall.entities),
                 memory_gap_turns=len(recall.gap))
        return recall

    async def _recall(self, session, previous, at):
        k, meta, summary, entities = await self._current(session, previous, at)
        if not meta:
            return Recall.from_state(previous.get('session_memory'), 'empty')
        upto, covered = int(summary.get('upto_seq', 0)), int(summary.get('covered_messages', 0))
        outside = outside_messages(int(meta['message_count']), covered, self.window)
        gap = []
        if outside and self.summarize:
            # Bridge turns the summary has not reached yet, so nothing is forgotten in between.
            ids = await self.redis.zrangebyscore(k.order, f'({upto}', '+inf', start=0, num=min(outside, 2 * self.trigger))
            rows = await self.redis.hmget(k.turns, ids) if ids else []
            gap = gap_turns([json.loads(row) for row in rows if row], outside)
        return Recall(summary=summary.get('text') or None, upto_seq=upto, covered=covered, gap=gap,
                      entities=json.loads(entities or '[]'), message_count=int(meta['message_count']), status='ok')

    @observed('memory.transcript', output=False)
    async def transcript(self, session, values, at=None):
        """Stored conversation for /history, oldest first; None means read the checkpoint."""
        return await self._guard('transcript', lambda: self._transcript(session, values or {}, at), max(self.timeout, 0.5))

    async def _transcript(self, session, values, at):
        k, meta, _, _ = await self._current(session, values, at)
        ids = await self.redis.zrange(k.order, 0, -1) if meta else []
        if not ids:
            return None
        rows = await self.redis.hmget(k.turns, ids)
        return [{'role': m['role'], 'content': m['content'], 'name': m['name']}
                for row in rows if row for m in json.loads(row)['messages']]

    async def metas(self, rows):
        """Session list summaries. Read-only: sessions are seeded under their lock elsewhere."""
        rows = list(rows)
        async def read():
            async with self.redis.pipeline(transaction=False) as pipe:
                for row in rows:
                    pipe.hgetall(self._keys(row['session_id']).meta)
                values = await pipe.execute()
            # A meta that missed the latest run is stale; that session uses its checkpoint.
            return {row['session_id']: meta for row, meta in zip(rows, values)
                    if meta and meta.get('generation') == str(row.get('generation'))
                    and meta.get('last_run_id') == row.get('thread_id')}
        return (await self._guard('metas', read) if rows else None) or {}

    async def forget(self, session_id):
        k = self._keys(session_id)
        await self._guard('forget', lambda: self.redis.unlink(*k.data, k.lock))

    async def purge_deleted(self, store):
        """Remove memory of cleared sessions whose delete could not reach Redis."""
        started = datetime.now(timezone.utc)
        rows = await store.deleted_sessions(self._purged_since or started - timedelta(seconds=self.ttl))
        failed = False
        for row in rows:
            k = self._keys(row['session_id'])
            async def purge():
                try:
                    async with self.redis.pipeline(transaction=True) as pipe:
                        await pipe.watch(k.meta)
                        generation = await pipe.hget(k.meta, 'generation')
                        if generation is not None and int(generation) > int(row['generation']):
                            return False  # reused session: its new generation is live
                        pipe.multi()
                        pipe.unlink(*k.data, k.lock)
                        await pipe.execute()
                        return True
                except WatchError:
                    return False
            failed = failed or await self._guard('purge', purge) is None
        if not failed:
            self._purged_since = started - timedelta(minutes=1)
        return len(rows)

    def _maybe_summarize(self, session_id, generation, message_count, covered):
        if (not self.summarize or session_id in self._tasks
                or outside_messages(message_count, covered, self.window) < 2 * self.trigger):
            return
        # A fresh context: the summary outlives the request and is traced on its own.
        task = asyncio.get_running_loop().create_task(self._summarize(session_id, generation), context=contextvars.Context())
        self._tasks[session_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(session_id, None))

    @observed('memory.summarize', output=False)
    async def _summarize(self, session_id, generation):
        k, token = self._keys(session_id), uuid4().hex
        try:
            # One summarizer per session across processes; the lock expires if a worker dies.
            if not await self.redis.set(k.lock, token, nx=True, px=SUMMARY_LOCK_MS):
                return
            try:
                for _ in range(FOLD_ROUNDS):
                    if not await self._fold(k, generation):
                        break
            finally:
                async with self.redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(k.lock)
                    if await pipe.get(k.lock) == token:
                        pipe.multi()
                        pipe.delete(k.lock)
                        await pipe.execute()
        except Exception as exc:
            logger.warning('session_memory_failed op=summarize error_type=%s', type(exc).__name__)

    async def _fold(self, k, generation):
        meta, summary, _ = await self._read(k)
        if not meta or int(meta.get('generation', 0)) != generation:
            return False
        upto, covered = int(summary.get('upto_seq', 0)), int(summary.get('covered_messages', 0))
        outside = outside_messages(int(meta['message_count']), covered, self.window)
        ids = await self.redis.zrangebyscore(k.order, f'({upto}', '+inf', start=0, num=min(outside, FOLD_TURNS)) if outside else []
        rows = await self.redis.hmget(k.turns, ids) if ids else []
        batch = fold_plan([json.loads(row) for row in rows if row], outside, FOLD_CHARS)
        text = await self._condense(summary.get('text'), batch) if batch else None
        if not text:
            return False
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(k.meta, k.summary)
                current = await pipe.hgetall(k.summary)
                if (await pipe.hget(k.meta, 'generation') != str(generation) or int(current.get('upto_seq', 0)) != upto
                        or int(current.get('covered_messages', 0)) != covered):
                    return False
                pipe.multi()
                pipe.hset(k.summary, mapping={'text': text, 'upto_seq': batch[-1]['seq'], 'generation': generation,
                                              'covered_messages': covered + sum(len(t['messages']) for t in batch),
                                              'updated_at': _now()})
                pipe.expire(k.summary, self.ttl)
                await pipe.execute()
        except WatchError:
            return False  # a concurrent trim or clear won; a later turn retries
        return True

    async def _condense(self, previous, turns):
        conversation = [{'vai': 'Người dùng' if m['role'] == 'human' else 'Trợ lý', 'noi_dung': m['content']}
                        for turn in turns for m in turn['messages']]
        result = await self.models.get('summary').ainvoke([
            SystemMessage(content=SUMMARY_PROMPT.format(limit=self.summary_chars)),
            HumanMessage(content=json.dumps({'tom_tat_cu': previous or '', 'cac_luot_moi': conversation}, ensure_ascii=False)),
        ], config=graph_config())
        text = (result.content if isinstance(result.content, str) else '').strip()
        annotate(input_count=len(turns), output_count=len(text), truncated=len(text) > self.summary_chars)
        return text[:self.summary_chars] or None
