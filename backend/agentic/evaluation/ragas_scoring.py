"""Chấm Ragas cho bản ghi RAG (`RetrievalRecord` JSONL do `rag_suite.export_ragas` xuất) trong venv riêng.

Ragas 0.4.x cần `openai` < 3.4 (qua instructor), xung đột với runtime agent (openai 3.33). Vì vậy bước chấm chạy
trong `.venv-ragas` và chỉ đọc file hợp đồng; không import runtime agent:

    .venv-ragas/bin/python backend/agentic/evaluation/ragas_scoring.py ragas-input.jsonl --out ragas-scores.jsonl

Số đo (API `ragas.metrics.collections`, không dùng lớp metric cũ đã deprecate):
    faithfulness, answer_relevancy, context_precision (không cần tham chiếu)    — mọi bản ghi có câu trả lời
    context_recall, factual_correctness                                      — chỉ khi có reference_answer do người
                                                                               kiểm chứng; không có thì ghi "không tính"
Judge: RAGAS_JUDGE_MODEL / RAGAS_JUDGE_BASE_URL / RAGAS_JUDGE_API_KEY (OpenAI-compatible); embedding cho
answer_relevancy: RAGAS_EMBEDDING_MODEL / RAGAS_EMBEDDING_BASE_URL / RAGAS_EMBEDDING_API_KEY. Tốn credit.
"""

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path

VERSION = "ragas-bridge-1.0"
REFERENCE_FREE = ("faithfulness", "answer_relevancy", "context_precision")
REFERENCE_BASED = ("context_recall", "factual_correctness")


def judge_config():
    return {
        "judge_model": os.environ.get("RAGAS_JUDGE_MODEL"),
        "judge_base_url": os.environ.get("RAGAS_JUDGE_BASE_URL"),
        "embedding_model": os.environ.get("RAGAS_EMBEDDING_MODEL"),
        "embedding_base_url": os.environ.get("RAGAS_EMBEDDING_BASE_URL"),
        "ragas_version": _ragas_version(),
        "bridge_version": VERSION,
    }


def _ragas_version():
    try:
        import ragas

        return ragas.__version__
    except Exception:  # noqa: BLE001
        return None


def build_metrics(llm, embeddings=None):
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithoutReference,
        ContextRecall,
        FactualCorrectness,
        Faithfulness,
    )

    metrics = {
        "faithfulness": Faithfulness(llm=llm),
        "context_precision": ContextPrecisionWithoutReference(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "factual_correctness": FactualCorrectness(llm=llm),
    }
    if embeddings is not None:
        metrics["answer_relevancy"] = AnswerRelevancy(llm=llm, embeddings=embeddings)
    return metrics


def live_models():
    """Judge và embedding OpenAI-compatible từ biến môi trường; None nếu chưa cấu hình (bị chặn, không đoán)."""
    model, base_url, key = (
        os.environ.get(k)
        for k in ("RAGAS_JUDGE_MODEL", "RAGAS_JUDGE_BASE_URL", "RAGAS_JUDGE_API_KEY")
    )
    if not (model and base_url and key):
        return None, None, "RAGAS_JUDGE_MODEL/RAGAS_JUDGE_BASE_URL/RAGAS_JUDGE_API_KEY not set"
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory

    llm = llm_factory(model, client=AsyncOpenAI(base_url=base_url, api_key=key))
    embeddings = None
    e_model, e_url, e_key = (
        os.environ.get(k)
        for k in ("RAGAS_EMBEDDING_MODEL", "RAGAS_EMBEDDING_BASE_URL", "RAGAS_EMBEDDING_API_KEY")
    )
    if e_model and e_url and e_key:
        from ragas.embeddings import embedding_factory

        embeddings = embedding_factory(
            "openai", model=e_model, client=AsyncOpenAI(base_url=e_url, api_key=e_key)
        )
    return llm, embeddings, None


def _value(result):
    value = getattr(result, "value", result)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else round(value, 4)


async def score_record(record, metrics):
    """Điểm EvaluationScore (dict JSON) cho một bản ghi; số đo cần tham chiếu chỉ khi có đáp án đã kiểm chứng."""
    question, answer = record["query"], record.get("answer")
    contexts = [c.get("text") or "" for c in record.get("final_contexts") or [] if c.get("text")]
    reference = record.get("reference_answer")
    out = []

    def score(name, value, explanation=None):
        out.append(
            {
                "case_id": record["case_id"],
                "name": name,
                "value": value,
                "data_type": "NUMERIC",
                "passed": None,
                "gate": "quality",
                "explanation": explanation,
                "evaluator": f"ragas.{name}",
                "evaluator_version": f"{VERSION}/ragas-{_ragas_version()}",
                "trace_id": None,
            }
        )

    if not answer or not contexts:
        return out
    calls = {
        "faithfulness": lambda m: m.ascore(
            user_input=question, response=answer, retrieved_contexts=contexts
        ),
        "context_precision": lambda m: m.ascore(
            user_input=question, response=answer, retrieved_contexts=contexts
        ),
        "answer_relevancy": lambda m: m.ascore(user_input=question, response=answer),
        "context_recall": lambda m: m.ascore(
            user_input=question, retrieved_contexts=contexts, reference=reference
        ),
        "factual_correctness": lambda m: m.ascore(response=answer, reference=reference),
    }
    for name, metric in metrics.items():
        if name in REFERENCE_BASED and not reference:
            score(name, None, "not computed: no human-verified reference answer")
            continue
        try:
            score(name, _value(await calls[name](metric)))
        except Exception as exc:  # noqa: BLE001 - một số đo lỗi không xoá các số đo khác
            score(name, None, f"judge error: {type(exc).__name__}")
    return out


async def score_file(path, metrics, *, limit=None):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    scores = []
    for record in records[:limit] if limit else records:
        scores.extend(await score_record(record, metrics))
    return records, scores


def summarize(scores):
    summary = {}
    for name in (*REFERENCE_FREE, *REFERENCE_BASED):
        values = [s["value"] for s in scores if s["name"] == name and s["value"] is not None]
        summary[name] = round(sum(values) / len(values), 4) if values else None
        summary[f"{name}_n"] = len(values)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("records")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    llm, embeddings, blocked = live_models()
    if blocked:
        print(json.dumps({"status": "blocked", "reason": blocked, "exit_code": 4}))
        return 4
    _, scores = asyncio.run(
        score_file(args.records, build_metrics(llm, embeddings), limit=args.limit)
    )
    Path(args.out).write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in scores))
    print(
        json.dumps(
            {"status": "scored", "judge": judge_config(), "summary": summarize(scores)}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
