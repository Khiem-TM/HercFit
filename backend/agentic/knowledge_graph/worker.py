"""Postgres transactional outbox consumer and administrative commands.

Run from backend/: python -m agentic.knowledge_graph.worker run
All commands use the backend PostgreSQL advisory lock, including when the agent
database is separate. An event is acknowledged only after its graph commit.
"""
from agentic.observability import observer, outcome, annotate
from agentic.observability.persistence import worker_context
import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .driver import create_driver, value
from .models import ProjectionEvent
from .projection import MODEL_SOURCES, Projector

log = logging.getLogger(__name__)
LOCK_KEY = 'hercfit-knowledge-graph-projection-v1'
EVENT_COLUMNS = 'event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload,trace_context,attempts'


class Worker:
    def __init__(self, settings, *, driver=None):
        self.settings = settings
        self.driver = driver or create_driver(settings)
        self.projector = Projector(self.driver, settings)
        agent_dsn = value(settings, 'AGENT_DATABASE_URL')
        backend_dsn = value(settings, 'KG_BACKEND_DATABASE_URL') or agent_dsn
        self.dsns = list(dict.fromkeys([backend_dsn, agent_dsn]))
        self.coordinator_dsn = backend_dsn
        self.agent_dsn = agent_dsn

    @asynccontextmanager
    async def exclusive(self):
        async with await AsyncConnection.connect(self.coordinator_dsn, autocommit=True, row_factory=dict_row) as conn:
            row = await (await conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired', (LOCK_KEY,))).fetchone()
            if not row['acquired']:
                yield False
                return
            try:
                yield True
            finally:
                await conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (LOCK_KEY,))

    async def close(self):
        await self.driver.close()
        await observer().close()

    async def consume_once(self):
        async with self.exclusive() as acquired:
            if not acquired:
                return 0
            return await self._consume_locked()

    async def _consume_locked(self):
        count = 0
        batch = value(self.settings, 'KG_WORKER_BATCH_SIZE', 100)
        maximum_lag = 0.0
        attempted = 0
        touched = set()
        for dsn in self.dsns:
            async with await AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
                # Ordering affects fairness only, never correctness; projector
                # source-version guards tolerate commit and delivery reordering.
                events = await (await conn.execute(f'''
                    SELECT {EVENT_COLUMNS} FROM kg_outbox
                    WHERE delivered_at IS NULL AND available_at<=now()
                    ORDER BY occurred_at,event_id LIMIT %s
                ''', (batch,))).fetchall()
                for row in events:
                    attempted += 1
                    event_id = row['event_id']
                    try:
                        event = ProjectionEvent.model_validate(row)
                        with worker_context('worker.kg_projection', row.get('trace_context'), event_id=str(event_id), retry_count=row.get('attempts',0), queue_wait_ms=max(0,(datetime.now(timezone.utc)-row['occurred_at']).total_seconds()*1000)):
                            await self.projector.apply(event)
                    except Exception as exc:
                        # Do not persist the exception text: driver errors may
                        # contain sensitive query parameters or connection URLs.
                        await conn.execute('''UPDATE kg_outbox SET attempts=attempts+1,
                            last_error=%s,available_at=now()+make_interval(secs=>LEAST(300,POWER(2,LEAST(attempts+1,8)))::int)
                            WHERE event_id=%s''', (type(exc).__name__, event_id))
                        log.warning('kg_projection_failed error_type=%s', type(exc).__name__)
                        continue
                    # A crash here causes redelivery; the graph version guard
                    # makes the already-committed projection a no-op.
                    await conn.execute('''UPDATE kg_outbox SET delivered_at=now(),last_error=NULL
                        WHERE event_id=%s''', (event_id,))
                    count += 1
                    if event.source == 'backend' and event.aggregate_type in MODEL_SOURCES and event.owner_id:
                        touched.add(event.owner_id)
                lag = await (await conn.execute('''SELECT COALESCE(MAX(EXTRACT(EPOCH FROM (now()-occurred_at))*1000),0) AS lag
                    FROM kg_outbox WHERE delivered_at IS NULL''')).fetchone()
                maximum_lag = max(maximum_lag, float(lag['lag']))
        await self.refresh_models(touched)
        await self.projector.query("""
            MATCH (s:KGState {key:'main'}) SET s.projection_lag_ms=$lag,s.last_poll_at=$time
        """, lag=maximum_lag, time=datetime.now(timezone.utc).isoformat())
        if attempted or (maximum_lag > 0 and monotonic()-getattr(self, '_last_trace_heartbeat', 0) >= 300):
            self._last_trace_heartbeat = monotonic()
            with worker_context('worker.kg_batch', projection_lag_ms=maximum_lag, input_count=attempted, output_count=count):
                pass
        log.info('kg_projection_batch delivered=%d projection_lag_ms=%.2f', count, maximum_lag)
        return count

    async def refresh_models(self, owners):
        """Derived knowledge is rebuildable: a failure is logged and retried by maintenance."""
        refreshed = 0
        for owner in sorted(owners):
            try:
                refreshed += bool(await self.projector.refresh_model(owner))
            except Exception as exc:
                log.warning('kg_model_refresh_failed error_type=%s', type(exc).__name__)
        return refreshed

    @asynccontextmanager
    async def agent_pool(self):
        async with AsyncConnectionPool(self.agent_dsn, min_size=1,max_size=3,open=False,
                                       kwargs={'autocommit':True,'row_factory':dict_row}) as pool:
            await pool.open(wait=True)
            yield pool

    async def reconcile(self, limit=50):
        from agentic.services.memory.reconcile import reconcile_checkpoints
        async with self.agent_pool() as pool:
            return await reconcile_checkpoints(pool,limit=limit)

    async def snapshot(self):
        from agentic.services.memory.store import Store
        async with await AsyncConnection.connect(self.coordinator_dsn, autocommit=True) as conn:
            await conn.execute('SELECT kg_enqueue_snapshot()')
        async with self.agent_pool() as pool:
            from agentic.services.memory.reconcile import reconcile_checkpoints
            await reconcile_checkpoints(pool, limit=100000)
            await Store(pool).enqueue_kg_snapshot()

    async def pending(self):
        total = 0
        for dsn in self.dsns:
            async with await AsyncConnection.connect(dsn,autocommit=True) as conn:
                total += (await (await conn.execute('SELECT count(*) FROM kg_outbox WHERE delivered_at IS NULL')).fetchone())[0]
        return total

    async def retry(self):
        for dsn in self.dsns:
            async with await AsyncConnection.connect(dsn,autocommit=True) as conn:
                await conn.execute('''UPDATE kg_outbox SET available_at=now(),last_error=NULL,attempts=0
                    WHERE delivered_at IS NULL AND attempts>0''')

    async def backfill(self, *, rebuild=False):
        async with self.exclusive() as acquired:
            if not acquired:
                raise RuntimeError('Another projection worker is active; retry the command')
            await self.projector.initialize()
            # Readiness blocks partial retrieval during both initial snapshots
            # and rebuild. Tombstones survive in PostgreSQL, not graph memory.
            await self.projector.query("MATCH (s:KGState {key:'main'}) SET s.ready=false,s.generation=s.generation+1")
            if rebuild:
                await self.projector.query('MATCH (n) WHERE n:KGEntity OR n:KGOwner DETACH DELETE n')
            await self.snapshot()
            # Snapshot sources include authoritative tombstones. Replay these
            # before ordinary events, preventing late old executions or private
            # records from restoring deleted users or session generations.
            for dsn in self.dsns:
                async with await AsyncConnection.connect(dsn,autocommit=True,row_factory=dict_row) as conn:
                    rows = await (await conn.execute(f'''SELECT {EVENT_COLUMNS} FROM kg_outbox
                        WHERE operation='delete' AND aggregate_type IN ('User','Session')
                        ORDER BY aggregate_version DESC''')).fetchall()
                    for row in rows:
                        await self.projector.apply(ProjectionEvent.model_validate(row))
            await self.retry()
            while await self._consume_locked():
                pass
            if await self.pending():
                raise RuntimeError('Projection backlog contains failures; graph remains warming. Fix errors and rerun backfill.')
            await self.projector.prune()
            await self.refresh_models(await self.projector.stale_model_owners(limit=100000))
            await self.projector.query("MATCH (s:KGState {key:'main'}) SET s.ready=true")

    async def run(self, *, once=False):
        await self.projector.initialize()
        next_maintenance = 0
        while True:
            try:
                if monotonic() >= next_maintenance:
                    await self.reconcile()
                    await self.projector.prune()
                    # Day-relative windows (7 days, this week) move even without new events.
                    await self.refresh_models(await self.projector.stale_model_owners())
                    next_maintenance = monotonic() + 60
                await self.consume_once()
            except Exception as exc:
                with worker_context('worker.kg_poll_failed'):
                    outcome('failed', error_code=type(exc).__name__)
                log.warning('kg_worker_failed error_type=%s',type(exc).__name__)
                if once:
                    raise
            if once:
                return
            await asyncio.sleep(value(self.settings,'KG_WORKER_POLL_SECONDS',1))


async def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','backfill','rebuild','retry','reconcile'])
    parser.add_argument('--once',action='store_true',help='Process a single batch (run only)')
    parser.add_argument('--confirm-rebuild',action='store_true',help='Acknowledge deletion of derived graph data')
    options = parser.parse_args(args)
    if options.command == 'rebuild' and not options.confirm_rebuild:
        parser.error('rebuild requires --confirm-rebuild; PostgreSQL source records are retained')
    from agentic.core.app.config import AgentSettings
    settings = AgentSettings()
    worker = Worker(settings)
    try:
        if options.command == 'run':
            await worker.run(once=options.once)
        elif options.command in {'backfill','rebuild'}:
            await worker.backfill(rebuild=options.command=='rebuild')
        elif options.command == 'retry':
            async with worker.exclusive() as acquired:
                if not acquired:
                    raise RuntimeError('Another projection worker is active; retry the command')
                await worker.retry()
        else:
            await worker.reconcile(limit=100000)
    finally:
        await worker.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    asyncio.run(main())
