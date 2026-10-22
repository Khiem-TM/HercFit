from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import HTTPException
from psycopg.types.json import Jsonb


def payload_hash(tool, payload):
    return sha256(json.dumps([tool, payload], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

class Store:
    def __init__(self, pool, lock_pool=None):
        self.pool = pool
        self.lock_pool = lock_pool or pool

    async def ready(self):
        from agentic.migrations.runner import EXPECTED_SCHEMA_VERSION
        async with self.pool.connection() as conn:
            result = await (await conn.execute('SELECT version FROM agent_schema_version WHERE version=%s', (EXPECTED_SCHEMA_VERSION,))).fetchone()
            if not result:
                raise RuntimeError('Run python -m agentic.migrate before starting')

    @asynccontextmanager
    async def session(self, session_id, user_id, create=True):
        # A distributed lock covers each chat/confirm/history operation, including
        # graph checkpoint writes. Other workers cannot race a confirmation/edit.
        async with self.lock_pool.connection() as conn:
            lock = 'agent-session:' + session_id
            await conn.execute('SELECT pg_advisory_lock(hashtextextended(%s, 0))', (lock,))
            try:
                if create:
                    async with conn.transaction():
                        generation = await (await conn.execute('SELECT * FROM agent_session_generations WHERE session_id=%s FOR UPDATE', (session_id,))).fetchone()
                        if generation and str(generation['user_id']) != user_id:
                            raise HTTPException(404, 'Session not found')
                        await conn.execute('INSERT INTO agent_sessions(session_id,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', (session_id,user_id))
                        await conn.execute('''INSERT INTO agent_session_generations(session_id,user_id) VALUES (%s,%s)
                            ON CONFLICT (session_id) DO UPDATE SET
                            generation=agent_session_generations.generation + CASE WHEN agent_session_generations.deleted THEN 1 ELSE 0 END,
                            deleted=false, updated_at=now()''', (session_id,user_id))
                row = await (await conn.execute('''SELECT s.*,g.generation FROM agent_sessions s
                    JOIN agent_session_generations g USING(session_id) WHERE s.session_id=%s''', (session_id,))).fetchone()
                if not row or str(row['user_id']) != user_id:
                    raise HTTPException(404, 'Session not found')
                yield row
            finally:
                await conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s, 0))', (lock,))

    async def bind(self, session_id, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute('INSERT INTO agent_threads(thread_id,session_id) VALUES (%s,%s)', (thread_id,session_id))
            await conn.execute('UPDATE agent_sessions SET thread_id=%s WHERE session_id=%s', (thread_id, session_id))

    async def new_action(self, session_id, user_id, tool, payload, preview, expires_at, research_id=None, action_id=None):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                existing = await (await conn.execute('SELECT data FROM agent_actions WHERE action_id=%s', (action_id,))).fetchone() if action_id else None
                if existing:
                    return existing['data']
                revision = (await (await conn.execute('UPDATE agent_sessions SET revision=revision+1 WHERE session_id=%s RETURNING revision', (session_id,))).fetchone())['revision']
                action = dict(action_id=action_id or str(uuid4()), session_id=session_id, user_id=user_id, tool=tool,
                              payload=payload, preview=preview, payload_hash=payload_hash(tool,payload),
                              revision=revision, expires_at=expires_at.isoformat(), research_id=research_id)
                await conn.execute('INSERT INTO agent_actions(action_id,session_id,user_id,status,data) VALUES (%s,%s,%s,%s,%s)',
                                   (action['action_id'], session_id,user_id,'pending',Jsonb(action)))
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
                generation = await (await conn.execute('SELECT * FROM agent_session_generations WHERE session_id=%s FOR UPDATE', (session_id,))).fetchone()
                if (not generation or generation['deleted'] or str(generation['user_id']) != user_id
                        or generation['generation'] != state.get('session_generation',1)):
                    return
                thread = await (await conn.execute('''SELECT kg_checkpoint_id FROM agent_threads
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
                await conn.execute('UPDATE agent_threads SET kg_checkpoint_id=COALESCE(%s,kg_checkpoint_id),kg_checked_at=now() WHERE thread_id=%s AND session_id=%s',
                                   (checkpoint_id,state['run_id'],session_id))

    async def reconciliation_threads(self, limit=50):
        async with self.pool.connection() as conn:
            return await (await conn.execute('''SELECT thread_id,session_id,kg_checkpoint_id FROM agent_threads
                ORDER BY kg_checked_at,created_at LIMIT %s''', (limit,))).fetchall()

    async def checked_thread(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute('UPDATE agent_threads SET kg_checked_at=now() WHERE thread_id=%s', (thread_id,))

    async def enqueue_kg_snapshot(self):
        """Requeue source records for a rebuild without changing their revisions."""
        count = 0
        async with self.pool.connection() as conn:
            async with conn.transaction():
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
                'SELECT session_id, thread_id, revision, created_at FROM agent_sessions WHERE user_id=%s ORDER BY created_at DESC LIMIT %s',
                (user_id, limit)
            )).fetchall()
            return rows
