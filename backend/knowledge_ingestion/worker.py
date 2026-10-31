"""Durable ingestion worker. Leases fence late workers after recovery."""
from agentic.observability import observer, annotate
from agentic.observability.persistence import worker_context
from datetime import datetime, timezone
import asyncio
import json
from uuid import uuid4
from sqlalchemy import text
from core.database import get_db_session, close_crud_db_pool
from knowledge_ingestion.config import settings
from knowledge_ingestion.embedding import FPTEmbeddingClient
from knowledge_ingestion.ingestion import publish_ready
from knowledge_ingestion.preparation import embedding_text

async def claim(profile):
    token=uuid4()
    async with get_db_session() as session:
        row=(await session.execute(text('''UPDATE knowledge_jobs SET status='RUNNING',attempts=attempts+1,
            lease_token=:token,lease_until=now()+interval '60 seconds'
            WHERE id=(SELECT id FROM knowledge_jobs WHERE profile_id=:profile AND attempts<5
            AND ((status='QUEUED' AND available_at<=now()) OR (status='RUNNING' AND lease_until<now()))
            ORDER BY available_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *'''),{'token':token,'profile':profile})).mappings().first()
        await session.execute(text("UPDATE knowledge_jobs SET status='FAILED',error_code='LeaseExhausted' WHERE status='RUNNING' AND lease_until<now() AND attempts>=5"))
        return dict(row) if row else None

async def heartbeat(job):
    async with get_db_session() as session:
        result=await session.execute(text('''UPDATE knowledge_jobs SET lease_until=now()+interval '60 seconds'
            WHERE id=:id AND lease_token=:lease_token AND status='RUNNING' AND lease_until>now()'''),job)
        if result.rowcount!=1: raise RuntimeError('LeaseLost')

async def process(job, client):
    with worker_context('worker.embedding', job.get('trace_context'), job_id=str(job['id']), retry_count=job.get('attempts',1)-1, queue_wait_ms=max(0,(datetime.now(timezone.utc)-job.get('available_at',datetime.now(timezone.utc))).total_seconds()*1000)):
        work = asyncio.create_task(_process(job, client))
        async def renew():
            while True:
                await asyncio.sleep(20)
                await heartbeat(job)
        lease = asyncio.create_task(renew())
        try:
            done, _ = await asyncio.wait({work, lease}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return await work
            await lease  # propagate a lost lease and cancel in-flight API work
            raise RuntimeError('LeaseLost')
        finally:
            for task in (work, lease):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, lease, return_exceptions=True)

async def _process(job, client):
    async with get_db_session() as session:
        # The embedded text gets the same context header that prepare counted into the token budget.
        rows=(await session.execute(text('''SELECT c.id,c.content,c.heading,COALESCE(r.metadata->>'title',d.title) AS title,
            COALESCE((r.metadata->'processing'->>'contextual_header')::boolean,false) AS contextual
            FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id JOIN knowledge_documents d ON d.id=r.document_id
            WHERE c.revision_id=:revision_id AND NOT EXISTS (
                SELECT 1 FROM knowledge_embeddings e WHERE e.chunk_id=c.id AND e.profile_id=:profile_id)
            ORDER BY c.position'''),job)).mappings().all()
    # Existing vectors are reused after retries or restarts; completion is checked below.
    annotate(chunk_count=len(rows))
    batch_size = settings().KNOWLEDGE_EMBEDDING_BATCH_SIZE
    for start in range(0,len(rows),batch_size):
        await heartbeat(job)
        batch=rows[start:start+batch_size]
        vectors=await client.embed([embedding_text(r['title'],r['heading'],r['content'],r['contextual']) for r in batch],
                                   input_type='passage')
        async with get_db_session() as session:
            locked=(await session.execute(text('''SELECT id FROM knowledge_jobs WHERE id=:id AND lease_token=:lease_token
                AND status='RUNNING' AND lease_until>now() FOR UPDATE'''),job)).scalar_one_or_none()
            if not locked: raise RuntimeError('LeaseLost')
            for row,vector in zip(batch,vectors):
                await session.execute(text('''INSERT INTO knowledge_embeddings(chunk_id,profile_id,embedding)
                    VALUES (:chunk,:profile,CAST(:vector AS vector)) ON CONFLICT(chunk_id,profile_id)
                    DO UPDATE SET embedding=EXCLUDED.embedding'''),{'chunk':row['id'],'profile':job['profile_id'],'vector':json.dumps(vector)})
        await asyncio.sleep(settings().KNOWLEDGE_REQUEST_INTERVAL)
    async with get_db_session() as session:
        counts=(await session.execute(text('''SELECT count(*) AS total,
            count(*) FILTER (WHERE e.chunk_id IS NULL) AS missing FROM knowledge_chunks c
            LEFT JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile_id
            WHERE c.revision_id=:revision_id'''),job)).mappings().one()
        if not counts['total'] or counts['missing']:
            raise ValueError('IncompleteDocumentEmbeddings')
        result=await session.execute(text('''UPDATE knowledge_jobs SET status='INDEXED',lease_until=NULL,error_code=NULL
            WHERE id=:id AND lease_token=:lease_token AND status='RUNNING' AND lease_until>now()'''),job)
        if result.rowcount!=1: raise RuntimeError('LeaseLost')
        await publish_ready(session,job['revision_id'])

async def run(once=False):
    cfg=settings(); client=FPTEmbeddingClient(cfg)
    try:
        await client.embed(['Embedding preflight'])
        while True:
            job=await claim(cfg.profile_id)
            if job:
                try: await process(job,client)
                except Exception as exc:
                    async with get_db_session() as session:
                        await session.execute(text('''UPDATE knowledge_jobs SET status=CASE WHEN attempts>=5 THEN 'FAILED' ELSE 'QUEUED' END,
                            available_at=now()+make_interval(secs=>LEAST(300,CAST(power(2,attempts) AS integer))),
                            error_code=:error,lease_until=NULL WHERE id=:id AND lease_token=:lease_token AND status='RUNNING' '''),
                            {**job,'error':type(exc).__name__})
                    if once:
                        raise
            if once: return
            if not job: await asyncio.sleep(cfg.KNOWLEDGE_WORKER_POLL_SECONDS)
    finally:
        await client.close(); await observer().close(); await close_crud_db_pool()

if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Process at most one job')
    asyncio.run(run(once=parser.parse_args().once))
