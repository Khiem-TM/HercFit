"""CLI vận hành cơ sở tri thức RAG. Chạy từ backend/: python -m agentic.embedding.ingestion.cli --help"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx

from agentic.embedding.ingestion import repository
from agentic.embedding.ingestion.config import DATA_ROOT, INGESTION_ROOT, settings

REVIEW_ACTIONS = ("review", "approve", "reject", "stale", "delete")


def emit(value):
    print(json.dumps(value, default=str, ensure_ascii=False, indent=2))


def read_manifest(path):
    return repository.Manifest.model_validate_json(Path(path).read_text())


async def main(args):
    cfg = settings()
    # Chuẩn bị/kiểm tra không bao giờ mở kết nối DB và không bao giờ gửi nội dung sách tới API.
    if args.command == "fetch-tokenizer":
        from agentic.embedding.ingestion.tokenization import fetch_tokenizer

        emit({"tokenizer_path": str(fetch_tokenizer(cfg.KNOWLEDGE_TOKENIZER_PATH))})
    elif args.command == "prepare":
        from agentic.embedding.ingestion.preparation import prepare

        report = prepare(args.source, args.output, args.spec, cfg)
        emit(
            {k: v for k, v in report.items() if k != "warnings"}
            | {"warning_pages": len(report["warnings"])}
        )
    elif args.command == "validate":
        from agentic.embedding.ingestion.preparation import load_prepared

        _, rows = load_prepared(cfg, read_manifest(args.manifest))
        emit({"status": "ok", "chunks": len(rows)})
    elif args.command == "preflight":
        await preflight(cfg)
    elif args.command == "worker":
        from agentic.embedding.ingestion.worker import run

        await run(once=args.once)
    else:
        await database_command(args, cfg)


async def preflight(cfg):
    """Gọi thật embedding (query và passage) và rerank; chỉ in model, số chiều, endpoint và profile."""
    from agentic.embedding.core import RerankClient
    from agentic.embedding.ingestion.client import FPTEmbeddingClient

    client, reranker = FPTEmbeddingClient(cfg), RerankClient(cfg)
    try:
        query = await client.embed(["Phục hồi sau chạy marathon"], input_type="query")
        passage = await client.embed(["Recovery after marathon running."], input_type="passage")
        scores = await reranker.rerank(
            "Phục hồi sau chạy marathon",
            ["Recovery after marathon running.", "Pho is a noodle soup."],
        )
        emit(
            {
                "status": "ok",
                "provider": "fpt",
                "model": cfg.EMBEDDING_MODEL,
                "dimension": len(query[0]),
                "passage_dimension": len(passage[0]),
                "rerank_model": cfg.RERANK_MODEL,
                "rerank_orders_relevant_first": scores[0] > scores[1],
                "profile_id": cfg.profile_id,
                "base_url": cfg.EMBEDDING_BASE_URL,
            }
        )
    finally:
        await client.close()
        await reranker.close()


async def database_command(args, cfg):
    from core.database import close_crud_db_pool, get_db_session

    try:
        async with get_db_session() as session:
            if args.command == "enqueue":
                emit(
                    {
                        "revision_id": await repository.enqueue(
                            session, cfg, read_manifest(args.manifest)
                        )
                    }
                )
            elif args.command in REVIEW_ACTIONS:
                await repository.review(session, UUID(args.revision), args.command, args.reviewer)
            elif args.command == "activate":
                await repository.activate(session, cfg.profile_id)
            elif args.command == "reindex":
                await repository.reindex(session, cfg)
            elif args.command == "retry":
                await repository.retry_job(session, UUID(args.job))
            elif args.command == "verify":
                row = await repository.coverage(session, UUID(args.revision), cfg.profile_id)
                emit(row)
                if not row["chunks"] or row["chunks"] != row["embeddings"]:
                    raise ValueError("Embedding coverage incomplete")
            elif args.command == "status":
                emit(await repository.recent_status(session))
    finally:
        await close_crud_db_pool()


def parser():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser(
        "prepare", help="Clean, tokenize and write a reproducible bundle; no API/DB"
    )
    prep.add_argument("source")
    prep.add_argument("--output", default=str(DATA_ROOT / "input/lore-of-running"))
    prep.add_argument("--spec", default=str(INGESTION_ROOT / "manifests/lore-of-running.json"))
    sub.add_parser("fetch-tokenizer", help="Download pinned tokenizer only")
    sub.add_parser("worker", help="Embed queued revisions").add_argument(
        "--once", action="store_true", help="Process at most one job"
    )
    for command in ("enqueue", "validate"):
        sub.add_parser(command).add_argument("manifest")
    for action in REVIEW_ACTIONS:
        q = sub.add_parser(action)
        q.add_argument("revision")
        q.add_argument("--reviewer", required=True)
    sub.add_parser("retry").add_argument("job")
    sub.add_parser("verify").add_argument("revision")
    for action in ("preflight", "activate", "reindex", "status"):
        sub.add_parser(action)
    return p


if __name__ == "__main__":
    try:
        asyncio.run(main(parser().parse_args()))
    except httpx.HTTPStatusError as exc:
        raise SystemExit(
            f"Embedding API HTTP {exc.response.status_code}; check endpoint, model, key scope and quota"
        ) from None
    except httpx.RequestError as exc:
        raise SystemExit(f"Network error: {type(exc).__name__}") from None
