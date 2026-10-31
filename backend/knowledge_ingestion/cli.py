"""RAG knowledge-base operator CLI. Run from backend/: python -m knowledge_ingestion.cli --help"""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import text

from core.database import get_db_session, close_crud_db_pool
from knowledge_ingestion.config import settings, LOCAL_ROOT, DATA_ROOT
from knowledge_ingestion.embedding import FPTEmbeddingClient
from knowledge_ingestion.ingestion import Manifest, enqueue, review, activate, ensure_profile, enqueue_index
from knowledge_ingestion.preparation import prepare, load_prepared
from knowledge_ingestion.tokenization import fetch_tokenizer


def emit(value):
    print(json.dumps(value, default=str, ensure_ascii=False, indent=2))


async def main(args):
    cfg = settings()
    # Preparation/validation never open a DB connection and never send book text to an API.
    if args.command == 'fetch-tokenizer':
        emit({'tokenizer_path': str(fetch_tokenizer(cfg.KNOWLEDGE_TOKENIZER_PATH))})
        return
    if args.command == 'prepare':
        report = prepare(args.source, args.output, args.spec, cfg)
        emit({k: v for k, v in report.items() if k != 'warnings'} | {'warning_pages': len(report['warnings'])})
        return
    if args.command == 'worker':
        from knowledge_ingestion.worker import run
        await run(once=args.once)
        return
    if args.command == 'validate':
        manifest = Manifest.model_validate_json(Path(args.manifest).read_text())
        _, rows = load_prepared(cfg, manifest)
        emit({'status': 'ok', 'chunks': len(rows)})
        return
    try:
        if args.command == 'preflight':
            from embedding.rerank import RerankClient
            client, reranker = FPTEmbeddingClient(cfg), RerankClient(cfg)
            try:
                query = await client.embed(['Phục hồi sau chạy marathon'], input_type='query')
                passage = await client.embed(['Recovery after marathon running.'], input_type='passage')
                scores = await reranker.rerank('Phục hồi sau chạy marathon',
                                               ['Recovery after marathon running.', 'Pho is a noodle soup.'])
                emit({'status': 'ok', 'provider': 'fpt', 'model': cfg.EMBEDDING_MODEL,
                      'dimension': len(query[0]), 'passage_dimension': len(passage[0]),
                      'rerank_model': cfg.RERANK_MODEL, 'rerank_orders_relevant_first': scores[0] > scores[1],
                      'profile_id': cfg.profile_id, 'base_url': cfg.EMBEDDING_BASE_URL})
            finally:
                await client.close()
                await reranker.close()
            return
        async with get_db_session() as session:
            if args.command == 'enqueue':
                emit({'revision_id': await enqueue(session, cfg, Manifest.model_validate_json(Path(args.manifest).read_text()))})
            elif args.command in {'review', 'approve', 'reject', 'stale', 'delete'}:
                await review(session, UUID(args.revision), args.command, args.reviewer)
            elif args.command == 'activate':
                await activate(session, cfg.profile_id)
            elif args.command == 'reindex':
                await ensure_profile(session, cfg)
                revisions = (await session.execute(text("SELECT id FROM knowledge_revisions WHERE review_status IN ('APPROVED','REVIEWED')"))).scalars().all()
                for revision in revisions:
                    await enqueue_index(session, revision, cfg.profile_id)
            elif args.command == 'retry':
                await session.execute(text("UPDATE knowledge_jobs SET status='QUEUED',attempts=0,available_at=now(),error_code=NULL WHERE id=:id AND status='FAILED'"), {'id': UUID(args.job)})
            elif args.command == 'verify':
                row = (await session.execute(text('''SELECT r.id, r.review_status, d.active_revision=r.id AS published,
                    count(c.id) AS chunks, count(e.chunk_id) AS embeddings FROM knowledge_revisions r
                    JOIN knowledge_documents d ON d.id=r.document_id
                    LEFT JOIN knowledge_chunks c ON c.revision_id=r.id
                    LEFT JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile
                    WHERE r.id=:id GROUP BY r.id,d.active_revision'''),
                    {'id': UUID(args.revision), 'profile': cfg.profile_id})).mappings().one()
                emit(dict(row))
                if not row['chunks'] or row['chunks'] != row['embeddings']:
                    raise ValueError('Embedding coverage incomplete')
            elif args.command == 'status':
                rows = (await session.execute(text('''SELECT r.id,r.version,r.review_status,r.reviewer,j.profile_id,j.status,j.attempts,j.error_code
                    FROM knowledge_revisions r LEFT JOIN knowledge_jobs j ON j.revision_id=r.id ORDER BY r.created_at DESC LIMIT 100'''))).mappings().all()
                emit([dict(r) for r in rows])
    finally:
        await close_crud_db_pool()


def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare', help='Clean, tokenize and write a reproducible bundle; no API/DB')
    prep.add_argument('source')
    prep.add_argument('--output', default=str(DATA_ROOT / 'input/lore-of-running'))
    prep.add_argument('--spec', default=str(LOCAL_ROOT / 'manifests/lore-of-running.json'))
    sub.add_parser('fetch-tokenizer', help='Download pinned tokenizer only')
    sub.add_parser('worker', help='Embed queued revisions').add_argument('--once', action='store_true', help='Process at most one job')
    for command in ('enqueue', 'validate'):
        sub.add_parser(command).add_argument('manifest')
    for action in ('review', 'approve', 'reject', 'stale', 'delete'):
        q = sub.add_parser(action)
        q.add_argument('revision')
        q.add_argument('--reviewer', required=True)
    sub.add_parser('retry').add_argument('job')
    sub.add_parser('verify').add_argument('revision')
    for action in ('preflight', 'activate', 'reindex', 'status'):
        sub.add_parser(action)
    return p


if __name__ == '__main__':
    try:
        asyncio.run(main(parser().parse_args()))
    except httpx.HTTPStatusError as exc:
        raise SystemExit(f'Embedding API HTTP {exc.response.status_code}; check endpoint, model, key scope and quota') from None
    except httpx.RequestError as exc:
        raise SystemExit(f'Network error: {type(exc).__name__}') from None
