"""Đưa kết quả eval vào Langfuse (backend experiment/trace duy nhất) và lấy ứng viên hồi quy ra từ đó.

* `sync(run, report)`: tạo/cập nhật dataset `hercfit-<suite>` (item id tất định theo ca + dấu vân tay dataset), chạy
  `Langfuse.run_experiment` với đầu ra ĐÃ ghi (không chạy lại agent) để mỗi ca có một trace experiment mang điểm,
  điểm toàn lần chạy là run-level score; siêu dữ liệu gồm commit, release, dataset, model, prompt, graph, evaluator.
  Ca có `trace_id` thật (chạy live với --trace) còn nhận điểm gắn thẳng vào trace đó với `score_id` tất định
  (ghi lại cùng id là cập nhật, không nhân đôi). Một lần chạy chỉ được đồng bộ một lần (`.langfuse-synced`).
* `regression_candidates(...)`: trace có điểm thấp/lỗi → CHỈ id trace và siêu dữ liệu (không input/output) vào
  hàng đợi review; người review viết lại ca đã làm sạch vào golden dataset. Không bao giờ tự chép hội thoại sức khoẻ.
* `sync_model_prices(prices)`: đẩy bảng giá ĐÃ KIỂM CHỨNG (MODEL_PRICES) thành model definition để Langfuse tính
  chi phí; không có giá thì không tạo gì (chi phí "chưa biết", không phải 0).
"""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from evaluation.contracts import EvaluationReport, EvaluationRun

MARKER = ".langfuse-synced"


def client():
    """Client Langfuse từ cấu hình observability, hoặc (None, lý do)."""
    from agentic.observability.settings import ObservabilitySettings

    config = ObservabilitySettings()
    if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
        return None, "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not configured", config
    from langfuse import Langfuse

    return (
        Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY.get_secret_value(),
            base_url=config.LANGFUSE_BASE_URL,
            environment="evaluation",
            release=config.LANGFUSE_RELEASE,
            timeout=10,
        ),
        None,
        config,
    )


def item_id(suite, case_id, fingerprint):
    return str(uuid5(NAMESPACE_URL, f"hercfit-eval:{suite}:{case_id}:{fingerprint}"))


def score_id(experiment_id, case_id, name, repeat=0):
    return str(uuid5(NAMESPACE_URL, f"hercfit-score:{experiment_id}:{case_id}:{name}:{repeat}"))


def _value(score):
    if score.data_type == "BOOLEAN":
        return 1.0 if score.value else 0.0
    return score.value


def summary_output(record):
    """Đầu ra ghi lên trace experiment: cấu trúc lượt chạy, không văn bản tự do của người dùng."""
    keys = (
        "status",
        "route",
        "selected_agents",
        "intents",
        "route_rules",
        "latency_ms",
        "usage",
        "variant",
    )
    out = {k: record.get(k) for k in keys if k in record}
    if record.get("tools") is not None:
        out["tools"] = [
            {"name": t.get("name"), "outcome": t.get("outcome"), "executed": t.get("executed")}
            for t in record["tools"]
        ]
    if record.get("verified_state"):
        out["write_count"] = record["verified_state"].get("write_count")
    return out


def metadata(run: EvaluationRun, report: EvaluationReport):
    meta = run.metadata
    values = {
        "experiment_id": meta.experiment_id,
        "suite": meta.suite,
        "mode": meta.mode,
        "dataset": meta.dataset.name,
        "dataset_version": meta.dataset.version,
        "dataset_fingerprint": meta.dataset.fingerprint,
        "git_sha": meta.git_sha or "unknown",
        "git_dirty": str(meta.git_dirty),
        "release": meta.release or "unknown",
        "environment": meta.environment or "unknown",
        "graph_version": meta.graph_version or "unknown",
        "models": json.dumps(meta.models, ensure_ascii=False),
        "prompts": json.dumps(meta.prompt_versions),
        "rag_config": json.dumps(meta.rag_config),
        "jev_config": json.dumps(meta.jev_config),
        "evaluators": json.dumps(meta.evaluator_versions),
        "status": report.status,
        "started_at": meta.started_at.isoformat(),
    }
    return {k: str(v)[:200] for k, v in values.items()}


def sync(run: EvaluationRun, report: EvaluationReport, *, folder=None, langfuse=None, force=False):
    marker = Path(folder) / MARKER if folder else None
    if marker and marker.exists() and not force:
        return {
            "status": "skipped",
            "reason": "already synced",
            "experiment": marker.read_text().strip(),
        }
    reason = None
    if langfuse is None:
        langfuse, reason, _ = client()
    if langfuse is None:
        return {"status": "blocked", "reason": reason}
    from langfuse.experiment import Evaluation

    meta = run.metadata
    dataset_name = f"hercfit-{meta.suite}"
    langfuse.create_dataset(
        name=dataset_name,
        description=f"HercFit golden dataset ({meta.suite})",
        metadata={"dataset": meta.dataset.name, "version": meta.dataset.version},
    )
    ids = {}
    for result in run.results:
        case = result.case
        identifier = item_id(meta.suite, case.id, meta.dataset.fingerprint)
        if identifier not in ids.values():
            langfuse.create_dataset_item(
                dataset_name=dataset_name,
                id=identifier,
                input={"case_id": case.id, **case.input},
                expected_output=case.reference,
                metadata={
                    "severity": case.severity,
                    "tags": case.tags,
                    "dataset_version": meta.dataset.version,
                },
            )
        ids[case.id] = identifier
    dataset = langfuse.get_dataset(dataset_name)
    wanted = set(ids.values())
    items = [item for item in dataset.items if item.id in wanted]
    by_item = {ids[r.case.id]: r for r in run.results if r.repeat_index == 0}

    def task(*, item, **_):
        return summary_output(by_item[item.id].record)

    def evaluator(*, input, output, expected_output, metadata=None, **_):
        result = by_item[item_id(meta.suite, input["case_id"], meta.dataset.fingerprint)]
        return [
            Evaluation(
                name=s.name,
                value=_value(s),
                comment=(s.explanation or "")[:500] or None,
                data_type="NUMERIC" if s.data_type == "BOOLEAN" else s.data_type,
                metadata={"gate": s.gate, "evaluator": s.evaluator, "version": s.evaluator_version},
            )
            for s in result.scores
            if s.value is not None and s.data_type != "CATEGORICAL"
        ]

    def run_level(*, item_results, **_):
        return [
            Evaluation(name=f"run_{k}", value=float(v), data_type="NUMERIC")
            for k, v in report.aggregates.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]

    result = langfuse.run_experiment(
        name=f"hercfit-{meta.suite}-{meta.mode}",
        run_name=f"{meta.experiment_name}-{meta.experiment_id[:8]}",
        description=f"{meta.suite}/{meta.mode} @ {(meta.git_sha or 'unknown')[:12]}",
        data=items,
        task=task,
        evaluators=[evaluator],
        run_evaluators=[run_level],
        metadata=metadata(run, report),
        max_concurrency=8,
    )
    linked = 0
    for case_result in run.results:
        trace_id = (case_result.record or {}).get("trace_id")
        if not trace_id:
            continue
        for score in case_result.scores:
            if score.value is None or score.data_type == "CATEGORICAL":
                continue
            langfuse.create_score(
                name=score.name,
                value=_value(score),
                trace_id=trace_id,
                data_type="NUMERIC" if score.data_type == "BOOLEAN" else score.data_type,
                score_id=score_id(
                    meta.experiment_id, case_result.case.id, score.name, case_result.repeat_index
                ),
                comment=(score.explanation or "")[:500] or None,
                metadata={"experiment_id": meta.experiment_id, "gate": score.gate},
            )
            linked += 1
    langfuse.flush()
    experiment = {
        "dataset": dataset_name,
        "run_name": getattr(result, "run_name", None),
        "dataset_run_id": getattr(result, "dataset_run_id", None),
        "dataset_run_url": getattr(result, "dataset_run_url", None),
        "items": len(items),
        "trace_linked_scores": linked,
    }
    if marker:
        marker.write_text(json.dumps(experiment) + "\n")
    return {"status": "synced", **experiment}


def regression_candidates(
    langfuse=None, *, names=("task_success", "user_feedback"), max_value=0.0, since=None, limit=50
):
    """Trace có điểm ≤ max_value → ứng viên hồi quy (id + siêu dữ liệu, không nội dung) chờ người review."""
    reason = None
    if langfuse is None:
        langfuse, reason, _ = client()
    if langfuse is None:
        return {"status": "blocked", "reason": reason, "candidates": []}
    candidates = []
    for name in names:
        page = langfuse.api.scores.get_many(
            name=name, value_max=max_value, from_timestamp=since, limit=limit
        )
        for score in getattr(page, "data", []) or []:
            candidates.append(
                {
                    "trace_id": getattr(score, "trace_id", None),
                    "score": name,
                    "value": getattr(score, "value", None),
                    "environment": getattr(score, "environment", None),
                    "review_status": "pending",
                    "content_copied": False,
                }
            )
    return {"status": "ok", "candidates": candidates}


def sync_model_prices(prices, langfuse=None):
    """MODEL_PRICES {"provider/model": {"input_per_million", "output_per_million"}} → model definition Langfuse."""
    if not prices:
        return {"status": "skipped", "reason": "MODEL_PRICES empty: cost stays unknown (never 0)"}
    reason = None
    if langfuse is None:
        langfuse, reason, _ = client()
    if langfuse is None:
        return {"status": "blocked", "reason": reason}
    created = []
    for key, price in prices.items():
        model = key.split("/", 1)[-1]
        langfuse.api.models.create(
            model_name=model,
            match_pattern=f"(?i)^{model}$",
            unit="TOKENS",
            input_price=price["input_per_million"] / 1e6,
            output_price=price["output_per_million"] / 1e6,
        )
        created.append(model)
    return {"status": "synced", "models": created}
