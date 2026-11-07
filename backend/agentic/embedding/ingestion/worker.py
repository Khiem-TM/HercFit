"""Worker embed bền vững; chạy qua `cli worker`. Lease fence các worker đến muộn sau khi khôi phục."""

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from agentic.embedding.ingestion.client import FPTEmbeddingClient
from agentic.embedding.ingestion.config import settings
from agentic.embedding.ingestion.preparation import embedding_text
from agentic.embedding.ingestion.repository import publish_ready
from agentic.observability import annotate, observer
from agentic.observability.persistence import worker_context
from core.database import close_crud_db_pool, get_db_session

LEASE = "interval '60 seconds'"
HEARTBEAT_SECONDS = 20
MAX_ATTEMPTS = 5
# Điều kiện chung cho mọi lần ghi của worker: vẫn giữ lease hợp lệ của job.
HOLDS_LEASE = "id=:id AND lease_token=:lease_token AND status='RUNNING' AND lease_until>now()"


async def claim(profile):
    async with get_db_session() as session:
        row = (
            (
                await session.execute(
                    text(f"""UPDATE knowledge_jobs SET status='RUNNING',attempts=attempts+1,
            lease_token=:token,lease_until=now()+{LEASE}
            WHERE id=(SELECT id FROM knowledge_jobs WHERE profile_id=:profile AND attempts<{MAX_ATTEMPTS}
            AND ((status='QUEUED' AND available_at<=now()) OR (status='RUNNING' AND lease_until<now()))
            ORDER BY available_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *"""),
                    {"token": uuid4(), "profile": profile},
                )
            )
            .mappings()
            .first()
        )
        await session.execute(
            text(f"""UPDATE knowledge_jobs SET status='FAILED',error_code='LeaseExhausted'
            WHERE status='RUNNING' AND lease_until<now() AND attempts>={MAX_ATTEMPTS}""")
        )
        return dict(row) if row else None


async def heartbeat(job):
    async with get_db_session() as session:
        result = await session.execute(
            text(f"UPDATE knowledge_jobs SET lease_until=now()+{LEASE} WHERE {HOLDS_LEASE}"), job
        )
        if result.rowcount != 1:
            raise RuntimeError("LeaseLost")


async def process(job, client):
    now = datetime.now(timezone.utc)
    queue_wait_ms = max(0, (now - job.get("available_at", now)).total_seconds() * 1000)
    with worker_context(
        "worker.embedding",
        job.get("trace_context"),
        job_id=str(job["id"]),
        retry_count=job.get("attempts", 1) - 1,
        queue_wait_ms=queue_wait_ms,
    ):
        work = asyncio.create_task(_process(job, client))

        async def renew():
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                await heartbeat(job)

        lease = asyncio.create_task(renew())
        try:
            done, _ = await asyncio.wait({work, lease}, return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return await work
            await lease  # truyền tiếp lỗi mất lease và huỷ công việc API đang chạy
            raise RuntimeError("LeaseLost")
        finally:
            for task in (work, lease):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, lease, return_exceptions=True)


async def _process(job, client):
    async with get_db_session() as session:
        # Văn bản được embed nhận cùng phần đầu ngữ cảnh mà prepare đã tính vào ngân sách token.
        rows = (
            (
                await session.execute(
                    text("""SELECT c.id,c.content,c.heading,COALESCE(r.metadata->>'title',d.title) AS title,
            COALESCE((r.metadata->'processing'->>'contextual_header')::boolean,false) AS contextual
            FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id JOIN knowledge_documents d ON d.id=r.document_id
            WHERE c.revision_id=:revision_id AND NOT EXISTS (
                SELECT 1 FROM knowledge_embeddings e WHERE e.chunk_id=c.id AND e.profile_id=:profile_id)
            ORDER BY c.position"""),
                    job,
                )
            )
            .mappings()
            .all()
        )
    # Vector có sẵn được dùng lại sau khi thử lại hoặc khởi động lại; việc hoàn tất được kiểm tra bên dưới.
    annotate(chunk_count=len(rows))
    batch_size = settings().KNOWLEDGE_EMBEDDING_BATCH_SIZE
    for start in range(0, len(rows), batch_size):
        await heartbeat(job)
        batch = rows[start : start + batch_size]
        vectors = await client.embed(
            [
                embedding_text(r["title"], r["heading"], r["content"], r["contextual"])
                for r in batch
            ],
            input_type="passage",
        )
        async with get_db_session() as session:
            locked = (
                await session.execute(
                    text(f"SELECT id FROM knowledge_jobs WHERE {HOLDS_LEASE} FOR UPDATE"), job
                )
            ).scalar_one_or_none()
            if not locked:
                raise RuntimeError("LeaseLost")
            for row, vector in zip(batch, vectors):
                await session.execute(
                    text("""INSERT INTO knowledge_embeddings(chunk_id,profile_id,embedding)
                    VALUES (:chunk,:profile,CAST(:vector AS vector)) ON CONFLICT(chunk_id,profile_id)
                    DO UPDATE SET embedding=EXCLUDED.embedding"""),
                    {
                        "chunk": row["id"],
                        "profile": job["profile_id"],
                        "vector": json.dumps(vector),
                    },
                )
        await asyncio.sleep(settings().KNOWLEDGE_REQUEST_INTERVAL)
    async with get_db_session() as session:
        counts = (
            (
                await session.execute(
                    text("""SELECT count(*) AS total,
            count(*) FILTER (WHERE e.chunk_id IS NULL) AS missing FROM knowledge_chunks c
            LEFT JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile_id
            WHERE c.revision_id=:revision_id"""),
                    job,
                )
            )
            .mappings()
            .one()
        )
        if not counts["total"] or counts["missing"]:
            raise ValueError("IncompleteDocumentEmbeddings")
        result = await session.execute(
            text(
                f"UPDATE knowledge_jobs SET status='INDEXED',lease_until=NULL,error_code=NULL WHERE {HOLDS_LEASE}"
            ),
            job,
        )
        if result.rowcount != 1:
            raise RuntimeError("LeaseLost")
        await publish_ready(session, job["revision_id"])


async def fail(job, exc):
    """Trả job về hàng đợi với backoff luỹ thừa (tối đa 300 giây), hoặc FAILED khi hết lượt thử."""
    async with get_db_session() as session:
        await session.execute(
            text(f"""UPDATE knowledge_jobs
            SET status=CASE WHEN attempts>={MAX_ATTEMPTS} THEN 'FAILED' ELSE 'QUEUED' END,
            available_at=now()+make_interval(secs=>LEAST(300,CAST(power(2,attempts) AS integer))),
            error_code=:error,lease_until=NULL WHERE id=:id AND lease_token=:lease_token AND status='RUNNING' """),
            {**job, "error": type(exc).__name__},
        )


async def run(once=False):
    cfg = settings()
    client = FPTEmbeddingClient(cfg)
    try:
        await client.embed(["Embedding preflight"])
        while True:
            job = await claim(cfg.profile_id)
            if job:
                try:
                    await process(job, client)
                except Exception as exc:
                    await fail(job, exc)
                    if once:
                        raise
            if once:
                return
            if not job:
                await asyncio.sleep(cfg.KNOWLEDGE_WORKER_POLL_SECONDS)
    finally:
        await client.close()
        await observer().close()
        await close_crud_db_pool()
