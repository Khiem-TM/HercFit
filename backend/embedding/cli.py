"""Usage: PYTHONPATH=backend python -m embedding.cli --help"""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID
from sqlalchemy import text
from core.database import get_db_session, close_crud_db_pool
from embedding.config import settings
from embedding.client import EmbeddingClient
from embedding.ingestion import Manifest, enqueue, review, activate, ensure_profile, enqueue_index

async def main(args):
    cfg=settings()
    try:
        if args.command=='preflight':
            client=EmbeddingClient(cfg)
            try: await client.embed(['Chạy bộ và phục hồi. Running and recovery.'])
            finally: await client.close()
            print(json.dumps({'status':'ok','profile_id':cfg.profile_id})); return
        async with get_db_session() as session:
            if args.command=='enqueue':
                print(await enqueue(session,cfg,Manifest.model_validate_json(Path(args.manifest).read_text())))
            elif args.command in {'review','approve','reject','stale','delete'}:
                await review(session,UUID(args.revision),args.command,args.reviewer)
            elif args.command=='activate': await activate(session,cfg.profile_id)
            elif args.command=='reindex':
                await ensure_profile(session,cfg)
                revisions=(await session.execute(text("SELECT id FROM knowledge_revisions WHERE review_status IN ('APPROVED','REVIEWED')"))).scalars().all()
                for revision in revisions: await enqueue_index(session,revision,cfg.profile_id)
            elif args.command=='retry':
                await session.execute(text("UPDATE knowledge_jobs SET status='QUEUED',attempts=0,available_at=now(),error_code=NULL WHERE id=:id AND status='FAILED'"),{'id':UUID(args.job)})
            elif args.command=='status':
                rows=(await session.execute(text('''SELECT r.id,r.version,r.review_status,r.reviewer,j.profile_id,j.status,j.attempts,j.error_code
                    FROM knowledge_revisions r LEFT JOIN knowledge_jobs j ON j.revision_id=r.id ORDER BY r.created_at DESC LIMIT 100'''))).mappings().all()
                print(json.dumps([dict(r) for r in rows],default=str,ensure_ascii=False,indent=2))
    finally: await close_crud_db_pool()

def parser():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('enqueue').add_argument('manifest')
    for action in ('review','approve','reject','stale','delete'):
        q=sub.add_parser(action); q.add_argument('revision'); q.add_argument('--reviewer',required=True)
    sub.add_parser('retry').add_argument('job')
    for action in ('preflight','activate','reindex','status'): sub.add_parser(action)
    return p

if __name__=='__main__': asyncio.run(main(parser().parse_args()))
