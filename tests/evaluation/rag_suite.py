"""Bộ RAG thống nhất: truy hồi (tất định, theo nhãn trang của golden dataset) và sinh câu trả lời (để chấm Ragas),
tách riêng từng giai đoạn và từng biến thể pipeline.

Mỗi ca ghi một `RetrievalRecord` với ba giai đoạn: ứng viên sau hợp nhất (trước rerank), sau rerank và ngữ cảnh
cuối đưa cho LLM. Biến thể so sánh trên CÙNG dataset 87 ca (`datasets/rag_cases.jsonl`):

    vector                     chỉ dense (pgvector), không rerank
    bm25                       chỉ full-text (ts_rank_cd; đóng vai BM25), không rerank
    hybrid                     dense + full-text hợp nhất RRF, không rerank
    hybrid_rerank              + cross-encoder rerank (cấu hình production)
    hybrid_rerank_multiquery   + truy vấn diễn đạt lại do người viết trong dataset (`queries`), không phải LLM viết lại

KG (đồ thị cá nhân) là pipeline khác: có/không KG được so ở bộ `kg` (kg_eval, biến thể no_kg/kg).
Nhãn vàng là khoảng trang + tiêu đề chương do người gán (rag_eval). Ca không có đáp án tham chiếu đã kiểm chứng thì
Ragas không tính context recall/factual correctness — không bao giờ dùng câu trả lời do LLM sinh làm tham chiếu.
"""

import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from evaluation import contracts, scoring
from evaluation.contracts import (
    CaseResult,
    ErrorRecord,
    EvaluationCase,
    EvaluationRun,
    EvaluationScore,
    RetrievalRecord,
    RetrievedContext,
    RunMetadata,
)

VERSION = "rag-1.0"
EVALUATION = Path(__file__).parent
CASES = EVALUATION / "datasets" / "rag_cases.jsonl"
DATASET_VERSION = "2026-10-30"
K = 10
VARIANTS = {
    "vector": {"keyword": False, "rerank": False, "multi": False},
    "bm25": {"dense": False, "rerank": False, "multi": False},
    "hybrid": {"rerank": False, "multi": False},
    "hybrid_rerank": {"multi": False},
    "hybrid_rerank_multiquery": {"multi": True},
}


def load_cases(path=CASES):
    rows = contracts.load_jsonl(path)
    cases = [
        EvaluationCase(
            id=row["id"],
            suite="rag",
            input={
                "query": row["query"],
                "queries": row.get("queries") or [],
                "lang": row.get("lang"),
            },
            reference={
                k: row[k]
                for k in ("expected_pages", "expected_heading", "kind", "reference_answer")
                if k in row
            },
            tags=[row["kind"], row.get("lang") or "?"],
            modes=["live"],
        )
        for row in rows
    ]
    return cases, contracts.dataset_info(
        "rag_cases",
        rows,
        version=DATASET_VERSION,
        path="tests/evaluation/datasets/rag_cases.jsonl",
    )


def contexts(items, *, with_text=False):
    out = []
    for rank, chunk in enumerate(items or [], 1):
        out.append(
            RetrievedContext(
                doc_id=str(chunk.get("document_id") or chunk.get("source_id") or chunk.get("id")),
                chunk_id=str(chunk.get("id")),
                rank=rank,
                score=chunk.get("score"),
                page=chunk.get("page"),
                page_end=chunk.get("page_end"),
                heading=chunk.get("heading"),
                text=(chunk.get("content") or chunk.get("text")) if with_text else None,
                source=chunk.get("source_url") or chunk.get("title"),
            )
        )
    return out


def score_case(case, record, ideal):
    """Số đo truy hồi tất định của một ca (relevance theo giao khoảng trang, như rag_eval)."""
    from evaluation.rag_eval import ranges_hit, relevant

    reference = {
        "expected_pages": case.reference.get("expected_pages") or [],
        "expected_heading": case.reference.get("expected_heading"),
    }
    final = [c.model_dump() for c in record.final_contexts]
    scores = []

    def add(name, value, passed=None):
        scores.append(
            EvaluationScore(
                case_id=case.id,
                name=name,
                value=value,
                data_type="BOOLEAN" if isinstance(value, bool) else "NUMERIC",
                passed=passed,
                evaluator="RetrievalMetrics",
                evaluator_version=VERSION,
            )
        )

    if case.reference.get("kind") == "out_of_domain":
        add("ood_rejected", not final, passed=not final)
        return scores
    flags = [relevant(c, reference) for c in final]
    metrics = scoring.retrieval_metrics(
        flags,
        found=ranges_hit(final[:5], reference),
        total=len(reference["expected_pages"]),
        ideal=ideal,
    )
    for name, value in metrics.items():
        add(name, round(value, 4))
    add(
        "chapter@3",
        float(any(c.get("heading") == reference["expected_heading"] for c in final[:3])),
    )
    # Giai đoạn truy hồi độc lập với rerank/chọn lọc: ứng viên có chứa trang đúng không.
    candidates = [c.model_dump() for c in record.candidates]
    if candidates:
        add("candidate_recall", float(any(relevant(c, reference) for c in candidates)))
    add("in_domain_rejected", not final, passed=bool(final))
    return scores


async def _ideal(session, case):
    from evaluation.rag_eval import available_relevant

    return await available_relevant(
        session, {"expected_pages": case.reference.get("expected_pages") or []}
    )


async def run_variant(variant, cases, dataset, *, limit=None, answers=False):
    from agentic.embedding.core import EmbeddingClient, RerankClient
    from agentic.embedding.core import settings as embedding_settings
    from agentic.embedding.retrieval.search import SearchOptions, SearchRequest
    from evaluation.rag_eval import attempt, search_once
    from core.database import close_crud_db_pool, get_db_session

    cfg = embedding_settings()
    client = EmbeddingClient(cfg)
    options = SearchOptions(debug=True, **VARIANTS[variant])
    reranker = RerankClient(cfg) if options.rerank and cfg.RERANK_ENABLED else None
    extra = {"options": options, **({"reranker": reranker} if reranker else {})}
    selected = cases[:limit] if limit else cases
    started_at = contracts.now()
    results = []
    drafter = _drafter() if answers else None
    try:
        async with get_db_session() as session:
            profile = (
                await session.execute(_text("SELECT id FROM knowledge_profiles WHERE active"))
            ).scalar()
        for case in selected:
            body = {"query": case.input["query"], "limit": K}
            if options.multi and case.input.get("queries"):
                body["queries"] = case.input["queries"]
            started = perf_counter()
            try:
                result, elapsed = await attempt(
                    lambda: search_once(SearchRequest(**body), cfg, client, extra)
                )
                diagnostics = result.get("diagnostics") or {}
                record = RetrievalRecord(
                    case_id=case.id,
                    query=case.input["query"],
                    queries=body.get("queries", []),
                    variant=variant,
                    candidates=contexts(diagnostics.get("fused")),
                    reranked=contexts(diagnostics.get("reranked")),
                    final_contexts=contexts(result["chunks"], with_text=True),
                    reference_answer=case.reference.get("reference_answer"),
                    corpus_version=str(profile),
                    index_version=f"{cfg.EMBEDDING_MODEL}@{cfg.EMBEDDING_REVISION}",
                    config={**VARIANTS[variant], "k": K, "rerank_status": result.get("rerank")},
                    latency_ms=round(elapsed, 1),
                    status=result.get("status"),
                )
                if drafter and case.reference.get("kind") == "in_domain" and result["chunks"]:
                    record.answer = await drafter(case, result["chunks"])
                async with get_db_session() as session:
                    ideal = (
                        await _ideal(session, case)
                        if case.reference.get("kind") == "in_domain"
                        else 0
                    )
                results.append(
                    CaseResult(
                        case=case,
                        record=record.model_dump(mode="json"),
                        scores=score_case(case, record, ideal),
                        duration_ms=round((perf_counter() - started) * 1000, 3),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    CaseResult(
                        case=case,
                        record={},
                        error=ErrorRecord(
                            category="infrastructure",
                            code=type(exc).__name__,
                            message=str(exc)[:200],
                        ),
                    )
                )
    finally:
        await client.close()
        if reranker:
            await reranker.close()
        await close_crud_db_pool()
    from evaluation.runner import git_state

    sha, dirty = git_state()
    metadata = RunMetadata(
        experiment_id=uuid4().hex,
        experiment_name=f"rag-{variant}",
        suite="rag",
        mode="retrieval",
        dataset=dataset,
        git_sha=sha,
        git_dirty=dirty,
        started_at=started_at,
        finished_at=contracts.now(),
        rag_config={
            "variant": variant,
            **VARIANTS[variant],
            "k": K,
            "corpus_profile": None,
            "embedding": f"{cfg.EMBEDDING_MODEL}@{cfg.EMBEDDING_REVISION}",
            "rerank_model": cfg.RERANK_MODEL if reranker else None,
        },
        evaluator_versions={"retrieval": VERSION},
    )
    return EvaluationRun(metadata=metadata, results=results)


def _text(sql):
    from sqlalchemy import text

    return text(sql)


def _drafter():
    """Bản nháp câu trả lời bằng model research của hệ thống (tốn credit) từ đúng ngữ cảnh đã truy hồi."""
    from agentic.agents import research_agent
    from agentic.core.app.config import agent_settings
    from agentic.core.llm import Models

    async def unbudgeted(*_args, **_kwargs):
        return None

    research_agent.reserve = unbudgeted
    agent = research_agent.ResearchV2(Models(agent_settings), None, None, agent_settings)

    async def draft(case, chunks):
        documents = {
            "kb:" + c["id"]: {**c, "url": c.get("source_url") or "", "source_id": "kb:" + c["id"]}
            for c in chunks
        }
        work = {
            "qa": True,
            "documents": documents,
            "plan": {"target": case.input["query"], "intent": "SPORTS_KNOWLEDGE_QA"},
        }
        result = await agent.draft({"run_id": "rag-eval", "decision": {"domain": None}}, work)
        return (
            " ".join(
                claim.text if hasattr(claim, "text") else str(claim) for claim in result.claims
            )
            or None
        )

    return draft


def export_ragas(run, path):
    """Bản ghi cho bộ chấm Ragas (venv riêng): chỉ ca có câu trả lời và ngữ cảnh."""
    rows = [
        r.record
        for r in run.results
        if r.record and r.record.get("answer") and r.record.get("final_contexts")
    ]
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return len(rows)
