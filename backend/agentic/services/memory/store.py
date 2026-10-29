from observability import durable_context
from observability.persistence import set_psycopg_context
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from hashlib import sha256
import json
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from agentic.services.memory.turns import turn_record


def payload_hash(tool, payload):
    return sha256(json.dumps([tool, payload], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

class SessionBusy(HTTPException):
    def __init__(self):
        super().__init__(409, 'Cuộc trò chuyện đang xử lý một yêu cầu khác; vui lòng thử lại sau ít giây.')


class Store:
    def __init__(self, pool, lock_pool=None, lease_seconds=180, wait_seconds=30):
        self.pool = pool
        self.lock_pool = lock_pool or pool  # kept for callers that still pass it
        self.lease_seconds, self.wait_seconds = lease_seconds, wait_seconds

    async def ready(self):
        from agentic.migrations.runner import EXPECTED_SCHEMA_VERSION
        async with self.pool.connection() as conn:
            result = await (await conn.execute('SELECT version FROM agent_schema_version WHERE version=%s', (EXPECTED_SCHEMA_VERSION,))).fetchone()
            if not result:
                raise RuntimeError('Run python -m agentic.scripts.migrate before starting')

    async def _acquire(self, session_id, user_id, create, token):
        """One short transaction: ownership checks, optional creation, then the lease."""
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                if create:
                    generation = await (await conn.execute('SELECT * FROM agent_session_generations WHERE session_id=%s FOR UPDATE', (session_id,))).fetchone()
                    if generation and str(generation['user_id']) != user_id:
                        raise HTTPException(404, 'Session not found')
                    await conn.execute('INSERT INTO agent_sessions(session_id,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', (session_id,user_id))
                    await conn.execute('''INSERT INTO agent_session_generations(session_id,user_id) VALUES (%s,%s)
                        ON CONFLICT (session_id) DO UPDATE SET
                        generation=agent_session_generations.generation + CASE WHEN agent_session_generations.deleted THEN 1 ELSE 0 END,
                        deleted=false, updated_at=now()''', (session_id,user_id))
                owner = await (await conn.execute('SELECT user_id FROM agent_sessions WHERE session_id=%s', (session_id,))).fetchone()
                if not owner or str(owner['user_id']) != user_id:
                    raise HTTPException(404, 'Session not found')
                acquired = await (await conn.execute('''UPDATE agent_sessions SET lease_token=%s,
                    lease_until=now() + make_interval(secs => %s)
                    WHERE session_id=%s AND (lease_until IS NULL OR lease_until < now()) RETURNING session_id''',
                    (token, self.lease_seconds, session_id))).fetchone()
                if not acquired:
                    return None
                return await (await conn.execute('''SELECT s.*,g.generation FROM agent_sessions s
                    JOIN agent_session_generations g USING(session_id) WHERE s.session_id=%s''', (session_id,))).fetchone()

    @asynccontextmanager
    async def session(self, session_id, user_id, create=True):
        # A timed lease serializes each chat/confirm/history/clear operation on a
        # conversation across workers, without holding a pooled connection while
        # the model runs. A crashed worker's lease simply expires.
        token = uuid4()
        deadline = monotonic() + self.wait_seconds
        while True:
            row = await self._acquire(session_id, user_id, create, token)
            if row is not None:
                break
            if monotonic() >= deadline:
                raise SessionBusy()
            await asyncio.sleep(0.2)
        try:
            yield row
        finally:
            async with self.pool.connection() as conn:
                await conn.execute('UPDATE agent_sessions SET lease_token=NULL, lease_until=NULL WHERE session_id=%s AND lease_token=%s',
                                   (session_id, token))

    async def bind(self, session_id, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute('INSERT INTO agent_threads(thread_id,session_id,needs_reconcile,last_run_at) VALUES (%s,%s,true,now())',
                               (thread_id,session_id))
            await conn.execute('UPDATE agent_sessions SET thread_id=%s WHERE session_id=%s', (thread_id, session_id))

    async def touch_thread(self, thread_id):
        """A resumed run (confirmation) may change the checkpoint: reconcile it later if needed."""
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE agent_threads SET needs_reconcile=true, last_run_at=now() WHERE thread_id=%s', (thread_id,))

    async def mark_reconciled(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE agent_threads SET needs_reconcile=false, kg_checked_at=now() WHERE thread_id=%s', (thread_id,))

    async def update_session_meta(self, session_id, *, title, last_message, message_count, status):
        async with self.pool.connection() as conn:
            await conn.execute('''UPDATE agent_sessions SET title=COALESCE(title, %s), last_message=%s,
                last_interaction_at=now(), message_count=%s, last_status=%s WHERE session_id=%s''',
                (title, last_message, message_count, status, session_id))

    async def consume_turn(self, user_id, *, turn_limit, token_limit, day=None):
        """Atomically count a new turn; False when today's turn or token budget is spent."""
        day = day or date.today()
        async with self.pool.connection() as conn:
            async with conn.transaction():
                row = await (await conn.execute('''INSERT INTO agent_usage_daily(user_id,day,turns) VALUES (%s,%s,0)
                    ON CONFLICT (user_id,day) DO UPDATE SET updated_at=now() RETURNING turns,input_tokens,output_tokens''',
                    (user_id, day))).fetchone()
                if (turn_limit and row['turns'] >= turn_limit) or (
                        token_limit and row['input_tokens'] + row['output_tokens'] >= token_limit):
                    return False
                await conn.execute('UPDATE agent_usage_daily SET turns=turns+1, updated_at=now() WHERE user_id=%s AND day=%s', (user_id, day))
                return True

    async def add_usage(self, user_id, input_tokens, output_tokens, day=None):
        async with self.pool.connection() as conn:
            await conn.execute('''INSERT INTO agent_usage_daily(user_id,day,input_tokens,output_tokens) VALUES (%s,%s,%s,%s)
                ON CONFLICT (user_id,day) DO UPDATE SET input_tokens=agent_usage_daily.input_tokens+EXCLUDED.input_tokens,
                output_tokens=agent_usage_daily.output_tokens+EXCLUDED.output_tokens, updated_at=now()''',
                (user_id, day or date.today(), int(input_tokens or 0), int(output_tokens or 0)))

    async def user_session_ids(self, user_id):
        async with self.pool.connection() as conn:
            rows = await (await conn.execute('SELECT session_id FROM agent_sessions WHERE user_id=%s', (user_id,))).fetchall()
            return [r['session_id'] for r in rows]

    async def stale_threads(self, older_than_days, limit=500):
        """Superseded per-turn threads older than the retention window (never a session's current thread)."""
        async with self.pool.connection() as conn:
            return await (await conn.execute('''SELECT t.thread_id FROM agent_threads t
                JOIN agent_sessions s USING(session_id)
                WHERE t.last_run_at < now() - make_interval(days => %s) AND t.thread_id IS DISTINCT FROM s.thread_id
                  AND NOT t.needs_reconcile
                ORDER BY t.last_run_at LIMIT %s''', (older_than_days, limit))).fetchall()

    async def forget_thread(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute('DELETE FROM agent_threads WHERE thread_id=%s', (thread_id,))

    async def new_action(self, session_id, user_id, tool, payload, preview, expires_at, research_id=None, action_id=None):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                existing = await (await conn.execute('SELECT data FROM agent_actions WHERE action_id=%s', (action_id,))).fetchone() if action_id else None
                if existing:
                    return existing['data']
                revision = (await (await conn.execute('UPDATE agent_sessions SET revision=revision+1 WHERE session_id=%s RETURNING revision', (session_id,))).fetchone())['revision']
                action = dict(action_id=action_id or str(uuid4()), session_id=session_id, user_id=user_id, tool=tool,
                              payload=payload, preview=preview, payload_hash=payload_hash(tool,payload),
                              revision=revision, expires_at=expires_at.isoformat(), research_id=research_id)
                await conn.execute('INSERT INTO agent_actions(action_id,session_id,user_id,status,data,trace_context) VALUES (%s,%s,%s,%s,%s,%s)',
                                   (action['action_id'], session_id,user_id,'pending',Jsonb(action),Jsonb(durable_context())))
                return action

    async def action(self, action_id):
        async with self.pool.connection() as conn:
            return await (await conn.execute('SELECT * FROM agent_actions WHERE action_id=%s', (action_id,))).fetchone()

    async def set_action(self, action_id, status, response=None):
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE agent_actions SET status=%s,response=COALESCE(%s,response) WHERE action_id=%s',
                               (status, Jsonb(response) if response is not None else None, action_id))

    async def invalidate(self, session_id):
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE agent_actions SET status='superseded' WHERE session_id=%s AND status='pending'", (session_id,))

    async def authorize(self, action):
        row = await self.action(action['action_id'])
        if not row or row['status'] not in {'approved','executed'}:
            raise HTTPException(409, 'Action is not approved')
        saved = row['data']
        fields = ['user_id','session_id','revision','tool','payload_hash']
        if any(saved[k] != action[k] for k in fields) or payload_hash(action['tool'],action['payload']) != saved['payload_hash']:
            raise HTTPException(409, 'Approved payload has changed')
        # Expiration checked at approval time. An accepted write can be retried
        # after an outage with its SAME idempotency key even after that deadline.
        return saved

    async def research(self, state, candidate):
        research_id = str(uuid4())
        async with self.pool.connection() as conn:
            await conn.execute('INSERT INTO agent_research(research_id,user_id,session_id,data) VALUES (%s,%s,%s,%s)',
                               (research_id,state['user_id'],state['session_id'],Jsonb(candidate)))
        return research_id

    async def link_research(self, research_id, resource_id):
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE agent_research SET resource_id=%s WHERE research_id=%s', (resource_id,research_id))

    async def delete_session(self, session_id):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                generation = await (await conn.execute('''UPDATE agent_session_generations SET deleted=true,updated_at=now()
                    WHERE session_id=%s RETURNING *''', (session_id,))).fetchone()
                if generation:
                    event_id = uuid5(NAMESPACE_URL, f"agent:Session:{session_id}:{generation['generation']}:delete")
                    await conn.execute('''INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Session',%s,%s,%s,'delete',now(),%s) ON CONFLICT DO NOTHING''',
                        (event_id,session_id,str(generation['user_id']),generation['generation'],
                         Jsonb({'session_id':session_id,'generation':generation['generation']})))
                await conn.execute('DELETE FROM agent_execution_records WHERE session_id=%s', (session_id,))
                await conn.execute('DELETE FROM agent_turn_records WHERE session_id=%s', (session_id,))
                await conn.execute('DELETE FROM agent_research_budgets WHERE session_id=%s', (session_id,))
                await conn.execute('DELETE FROM agent_research WHERE session_id=%s', (session_id,))
                await conn.execute('DELETE FROM agent_actions WHERE session_id=%s', (session_id,))
                await conn.execute('DELETE FROM agent_threads WHERE session_id=%s', (session_id,))
                await conn.execute('DELETE FROM agent_sessions WHERE session_id=%s', (session_id,))

    async def kg_retrieval_gate(self, user_id):
        """Current SQL ownership/generations gate stale graph episodes immediately."""
        async with self.pool.connection() as conn:
            rows = await (await conn.execute('SELECT session_id,generation,deleted FROM agent_session_generations WHERE user_id=%s', (user_id,))).fetchall()
        return {'blocked':False,
                'session_generations':{r['session_id']:r['generation'] for r in rows if not r['deleted']},
                'deleted_session_ids':[r['session_id'] for r in rows if r['deleted']]}

    async def record_execution_state(self, state, checkpoint_id=None):
        """Journal committed workflow observations and enqueue them atomically.

        Replaying a checkpoint is a no-op. An approved action that first failed
        and later succeeds produces a higher version of the same execution.
        """
        session_id, user_id = state.get('session_id'), state.get('user_id')
        if not session_id or not user_id:
            return
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn, state.get('trace_context'))
                generation = await (await conn.execute('SELECT * FROM agent_session_generations WHERE session_id=%s FOR UPDATE', (session_id,))).fetchone()
                if (not generation or generation['deleted'] or str(generation['user_id']) != user_id
                        or generation['generation'] != state.get('session_generation',1)):
                    return
                thread = await (await conn.execute('''SELECT kg_checkpoint_id,created_at FROM agent_threads
                    WHERE thread_id=%s AND session_id=%s FOR UPDATE''', (state['run_id'],session_id))).fetchone()
                if not thread:
                    return
                # LangGraph checkpoint IDs are monotonically ordered UUIDs.
                # A reconciler that read an older checkpoint must not replace a
                # later successful action observation with a previous failure.
                if checkpoint_id and thread['kg_checkpoint_id'] and checkpoint_id <= thread['kg_checkpoint_id']:
                    await conn.execute('UPDATE agent_threads SET kg_checked_at=now() WHERE thread_id=%s', (state['run_id'],))
                    return
                # Coalesce attempts of the same logical action within this state.
                records = {r['execution_id']:r for r in state.get('execution_records',[]) if r.get('execution_id')}
                for execution_id, record in records.items():
                    UUID(execution_id)
                    if record.get('status') not in {'succeeded','failed'}:
                        continue
                    data = {key:record.get(key) for key in ('execution_id','tool','status','duration_ms','occurred_at','resource_refs','error_code','template_id','template_version')}
                    data.update(run_id=state['run_id'],session_id=session_id,session_generation=generation['generation'])
                    row = await (await conn.execute('''INSERT INTO agent_execution_records
                        (execution_id,session_id,session_generation,user_id,run_id,occurred_at,data)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (execution_id) DO UPDATE SET data=EXCLUDED.data,
                        version=agent_execution_records.version+1,occurred_at=EXCLUDED.occurred_at
                        WHERE agent_execution_records.data IS DISTINCT FROM EXCLUDED.data
                        RETURNING version''', (execution_id,session_id,generation['generation'],user_id,state['run_id'],
                                               data['occurred_at'],Jsonb(data)))).fetchone()
                    if row:
                        event_id = uuid5(NAMESPACE_URL, f"agent:Execution:{execution_id}:{row['version']}")
                        await conn.execute('''INSERT INTO kg_outbox
                            (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                            VALUES (%s,'agent','Execution',%s,%s,%s,'upsert',%s,%s) ON CONFLICT DO NOTHING''',
                            (event_id,execution_id,user_id,row['version'],data['occurred_at'],Jsonb(data)))
                turn = turn_record(state)
                if turn:
                    turn.update(session_generation=generation['generation'], occurred_at=thread['created_at'].isoformat())
                    row = await (await conn.execute('''INSERT INTO agent_turn_records
                        (run_id,session_id,session_generation,user_id,occurred_at,data)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (run_id) DO UPDATE SET data=EXCLUDED.data,version=agent_turn_records.version+1
                        WHERE agent_turn_records.data IS DISTINCT FROM EXCLUDED.data
                        RETURNING version''', (state['run_id'],session_id,generation['generation'],user_id,
                                               thread['created_at'],Jsonb(turn)))).fetchone()
                    if row:
                        event_id = uuid5(NAMESPACE_URL, f"agent:Run:{state['run_id']}:{row['version']}")
                        await conn.execute('''INSERT INTO kg_outbox
                            (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                            VALUES (%s,'agent','Run',%s,%s,%s,'upsert',%s,%s) ON CONFLICT DO NOTHING''',
                            (event_id,state['run_id'],user_id,row['version'],thread['created_at'],Jsonb(turn)))
                await conn.execute('UPDATE agent_threads SET kg_checkpoint_id=COALESCE(%s,kg_checkpoint_id),kg_checked_at=now() WHERE thread_id=%s AND session_id=%s',
                                   (checkpoint_id,state['run_id'],session_id))

    async def reconciliation_threads(self, limit=50, grace_seconds=180):
        """Threads whose last run may have ended without journaling (worker crash).

        Runs journal themselves on completion; only flagged threads older than the
        grace period are read, so an idle system performs no checkpoint reads.
        """
        async with self.pool.connection() as conn:
            return await (await conn.execute('''SELECT thread_id,session_id,kg_checkpoint_id FROM agent_threads
                WHERE needs_reconcile AND last_run_at < now() - make_interval(secs => %s)
                ORDER BY last_run_at LIMIT %s''', (grace_seconds, limit))).fetchall()

    async def checked_thread(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE agent_threads SET kg_checked_at=now(), needs_reconcile=false WHERE thread_id=%s', (thread_id,))

    async def enqueue_kg_snapshot(self):
        """Requeue source records for a rebuild without changing their revisions."""
        count = 0
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                rows = await (await conn.execute('''SELECT e.* FROM agent_execution_records e
                    JOIN agent_session_generations g USING(session_id)
                    WHERE NOT g.deleted AND g.generation=e.session_generation''')).fetchall()
                for row in rows:
                    event_id = uuid5(NAMESPACE_URL, f"agent:Execution:{row['execution_id']}:{row['version']}")
                    await conn.execute('''INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Execution',%s,%s,%s,'upsert',%s,%s)
                        ON CONFLICT (source,aggregate_type,aggregate_id,aggregate_version,operation)
                        DO UPDATE SET delivered_at=NULL,attempts=0,last_error=NULL,available_at=now()''',
                        (event_id,str(row['execution_id']),str(row['user_id']),row['version'],row['occurred_at'],Jsonb(row['data'])))
                    count += 1
                turns = await (await conn.execute('''SELECT t.* FROM agent_turn_records t
                    JOIN agent_session_generations g USING(session_id)
                    WHERE NOT g.deleted AND g.generation=t.session_generation''')).fetchall()
                for row in turns:
                    event_id = uuid5(NAMESPACE_URL, f"agent:Run:{row['run_id']}:{row['version']}")
                    await conn.execute('''INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Run',%s,%s,%s,'upsert',%s,%s)
                        ON CONFLICT (source,aggregate_type,aggregate_id,aggregate_version,operation)
                        DO UPDATE SET delivered_at=NULL,attempts=0,last_error=NULL,available_at=now()''',
                        (event_id,row['run_id'],str(row['user_id']),row['version'],row['occurred_at'],Jsonb(row['data'])))
                    count += 1
                sessions = await (await conn.execute('SELECT * FROM agent_session_generations WHERE deleted OR generation>1')).fetchall()
                for row in sessions:
                    generation = row['generation'] if row['deleted'] else row['generation']-1
                    event_id = uuid5(NAMESPACE_URL, f"agent:Session:{row['session_id']}:{generation}:delete")
                    await conn.execute('''INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Session',%s,%s,%s,'delete',%s,%s)
                        ON CONFLICT (source,aggregate_type,aggregate_id,aggregate_version,operation)
                        DO UPDATE SET delivered_at=NULL,attempts=0,last_error=NULL,available_at=now()''',
                        (event_id,row['session_id'],str(row['user_id']),generation,row['updated_at'],
                         Jsonb({'session_id':row['session_id'],'generation':generation})))
                    count += 1
        return count

    async def threads(self,session_id):
        async with self.pool.connection() as conn:
            rows=await (await conn.execute('SELECT thread_id FROM agent_threads WHERE session_id=%s',(session_id,))).fetchall()
            return [r['thread_id'] for r in rows]

    async def list_sessions(self, user_id, limit=50):
        async with self.pool.connection() as conn:
            rows = await (await conn.execute(
                '''SELECT s.session_id, s.thread_id, s.revision, s.created_at, COALESCE(g.generation, 1) AS generation,
                          s.title, s.last_message, s.last_interaction_at, s.message_count, s.last_status
                   FROM agent_sessions s LEFT JOIN agent_session_generations g USING(session_id)
                   WHERE s.user_id=%s ORDER BY COALESCE(s.last_interaction_at, s.created_at) DESC LIMIT %s''',
                (user_id, limit)
            )).fetchall()
            return rows

    async def deleted_sessions(self, since):
        """Sessions cleared since a moment; their Redis memory must not outlive them."""
        async with self.pool.connection() as conn:
            return await (await conn.execute('SELECT session_id,generation FROM agent_session_generations WHERE deleted AND updated_at>=%s',
                                              (since,))).fetchall()
