"""Durable ingestion worker. Leases fence late workers after recovery."""
from observability import observer, annotate
from observability.persistence import worker_context
from datetime import datetime, timezone
import asyncio
import json
from uuid import uuid4
from sqlalchemy import text
from core.database import get_db_session, close_crud_db_pool
from embedding.config import settings
from embedding.client import EmbeddingClient
from embedding.ingestion import publish_ready

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
        return await _process(job, client)

async def _process(job, client):
    async with get_db_session() as session:
        rows=(await session.execute(text('''SELECT id,content FROM knowledge_chunks WHERE revision_id=:revision_id
            ORDER BY position'''),job)).mappings().all()
    if not rows: raise ValueError('EmptyDocument')
    annotate(chunk_count=len(rows))
    for start in range(0,len(rows),16):
        await heartbeat(job)
        batch=rows[start:start+16]
        vectors=await client.embed([r['content'] for r in batch])
        async with get_db_session() as session:
            locked=(await session.execute(text('''SELECT id FROM knowledge_jobs WHERE id=:id AND lease_token=:lease_token
                AND status='RUNNING' AND lease_until>now() FOR UPDATE'''),job)).scalar_one_or_none()
            if not locked: raise RuntimeError('LeaseLost')
            for row,vector in zip(batch,vectors):
                await session.execute(text('''INSERT INTO knowledge_embeddings(chunk_id,profile_id,embedding)
                    VALUES (:chunk,:profile,CAST(:vector AS vector)) ON CONFLICT(chunk_id,profile_id)
                    DO UPDATE SET embedding=EXCLUDED.embedding'''),{'chunk':row['id'],'profile':job['profile_id'],'vector':json.dumps(vector)})
    async with get_db_session() as session:
        result=await session.execute(text('''UPDATE knowledge_jobs SET status='INDEXED',lease_until=NULL,error_code=NULL
            WHERE id=:id AND lease_token=:lease_token AND status='RUNNING' AND lease_until>now()'''),job)
        if result.rowcount!=1: raise RuntimeError('LeaseLost')
        await publish_ready(session,job['revision_id'])

async def run(once=False):
    cfg=settings(); client=EmbeddingClient(cfg)
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
            if once: return
            if not job: await asyncio.sleep(cfg.KNOWLEDGE_WORKER_POLL_SECONDS)
    finally:
        await client.close(); await observer().close(); await close_crud_db_pool()

if __name__=='__main__': asyncio.run(run())
