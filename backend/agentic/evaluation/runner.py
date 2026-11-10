"""Chạy golden dataset qua Pydantic Evals trên graph thật và quy kết quả về hợp đồng `EvaluationRun`.

Pydantic Evals điều phối (ca, đồng thời, lặp lại, evaluator ca và evaluator toàn báo cáo); `GraphRuntimeAdapter`
thực thi graph LangGraph của HercFit; báo cáo của Pydantic Evals được chuyển sang hợp đồng trung lập để cổng chất
lượng, baseline và Langfuse không phụ thuộc định dạng của thư viện.
"""

import subprocess
from contextlib import nullcontext
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import ConfusionMatrixEvaluator

from agentic.evaluation import contracts
from agentic.evaluation.adapters.graph_runtime import (
    GraphRuntimeAdapter,
    graph_version,
    prompt_versions,
)
from agentic.evaluation.contracts import (
    CaseResult,
    ErrorRecord,
    EvaluationCase,
    EvaluationScore,
    RunMetadata,
)
from agentic.evaluation.evaluators import agent as agent_evaluators
from agentic.evaluation.evaluators import safety as safety_evaluators

EVALUATION = Path(__file__).parent
DATASETS = EVALUATION / "datasets"
GOLDEN = {"agent": DATASETS / "agent_golden.jsonl"}
DATASET_VERSION = {"agent": "2026-11-10.1"}
SAFETY_TAGS = {"safety", "authorization", "injection", "confirmation", "tool_policy"}
EVALUATOR_VERSIONS = {"agent": agent_evaluators.VERSION, "safety": safety_evaluators.VERSION}


def git_state():
    root = EVALUATION.parents[2]
    try:
        sha = (
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or None
        )
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        )
        return sha, dirty
    except Exception:  # noqa: BLE001 - chạy được cả khi không có git (container)
        import os

        return os.environ.get("GIT_COMMIT_SHA"), None


def load_cases(suite="agent", *, mode="deterministic", tags=None, ids=None, path=None):
    rows = contracts.load_jsonl(path or GOLDEN[suite])
    cases = [EvaluationCase(**row) for row in rows]
    cases = [c for c in cases if mode in c.modes]
    if tags:
        cases = [c for c in cases if set(c.tags) & set(tags)]
    if ids:
        cases = [c for c in cases if c.id in ids]
    selected = {c.id for c in cases}
    return cases, contracts.dataset_info(
        f"{suite}_golden",
        [r for r in rows if r["id"] in selected],
        version=DATASET_VERSION.get(suite, "unversioned"),
        path=(path or GOLDEN[suite]).relative_to(EVALUATION.parents[2]) if not path else path,
    )


def _score(case_id, result, kind, trace_id):
    name = result.name
    value = result.value
    data_type = {"assertion": "BOOLEAN", "score": "NUMERIC", "label": "CATEGORICAL"}[kind]
    source = getattr(result.source, "name", None) or type(result.source).__name__
    module = agent_evaluators if hasattr(agent_evaluators, source) else safety_evaluators
    return EvaluationScore(
        case_id=case_id,
        name=name,
        value=value,
        data_type=data_type,
        passed=bool(value) if kind == "assertion" else None,
        gate="hard_safety"
        if name in agent_evaluators.HARD_SAFETY
        else ("quality" if kind != "label" else "info"),
        explanation=result.reason,
        evaluator=source,
        evaluator_version=getattr(module, "VERSION", "unknown"),
        trace_id=trace_id,
    )


def to_results(report, cases):
    by_id = {c.id: c for c in cases}
    results = []
    repeats = {}
    for case in report.cases:
        case_id = case.source_case_name or case.name
        repeats[case_id] = repeats.get(case_id, -1) + 1
        record = case.output.model_dump(mode="json")
        trace = record.get("trace_id")
        scores = [_score(case_id, r, "assertion", trace) for r in case.assertions.values()]
        scores += [_score(case_id, r, "score", trace) for r in case.scores.values()]
        scores += [_score(case_id, r, "label", trace) for r in case.labels.values()]
        errors = record.get("errors") or []
        results.append(
            CaseResult(
                case=by_id[case_id],
                record=record,
                scores=scores,
                error=ErrorRecord(**errors[0]) if errors else None,
                repeat_index=repeats[case_id],
                duration_ms=round(case.task_duration * 1000, 3),
            )
        )
    for failure in report.failures:
        case_id = failure.source_case_name or failure.name
        results.append(
            CaseResult(
                case=by_id[case_id],
                record={},
                error=ErrorRecord(
                    category="infrastructure",
                    code="TaskFailed",
                    message=failure.error_message[:300],
                ),
            )
        )
    return results


async def run_agent_suite(
    mode="deterministic",
    *,
    tags=None,
    ids=None,
    repeat=1,
    concurrency=4,
    judge=False,
    trace=False,
    experiment_name=None,
    suite_label="agent",
):
    cases, dataset = load_cases("agent", mode=mode, tags=tags, ids=ids)
    notes = []
    if mode == "live":
        from agentic.evaluation.adapters.graph_runtime import live_models

        models, settings = live_models()
        adapter = GraphRuntimeAdapter("live", models=models, settings=settings)
        model_config = {
            role: str(getattr(settings, f"{role.upper()}_MODEL", None) or settings.DEFAULT_MODEL)
            for role in ("decision", "tool", "response", "research", "clarify", "summary")
        }
        jev = {"JEV_MODE": settings.JEV_MODE}
    else:
        adapter = GraphRuntimeAdapter("deterministic")
        model_config, jev = {"all_roles": "scripted"}, {"JEV_MODE": "off"}
    by_id = {c.id: c for c in cases}
    evaluators = [*agent_evaluators.agent_evaluators(), *safety_evaluators.safety_evaluators()]
    judge_config = {}
    if judge:
        extra, blocked = safety_evaluators.judge_evaluators()
        evaluators += extra
        judge_config = {
            "rubric_version": safety_evaluators.JUDGE_RUBRIC_VERSION,
            "blocked": blocked,
        }
        if blocked:
            notes.append("LLM judge not run: " + blocked)

    async def task(inputs):
        case = by_id[inputs["case_id"]]
        if trace:
            from agentic.observability import observer

            scope = observer().request("eval.case", "evaluation")
        else:
            scope = nullcontext(None)
        with scope as state:
            record = await adapter.run(case)
            if (
                state is not None
                and getattr(state, "sampled", False)
                and getattr(state.manager, "client", None)
            ):
                record.trace_id = state.trace_id
            return record

    dataset_obj = Dataset(
        name=f"hercfit-{suite_label}-{mode}",
        cases=[
            Case(
                name=c.id,
                inputs={**c.input, "case_id": c.id},
                expected_output=c.reference,
                metadata={
                    "severity": c.severity,
                    "tags": c.tags,
                    "expected_route": (c.reference.get("route") or [None])[0],
                },
            )
            for c in cases
        ],
        evaluators=evaluators,
        report_evaluators=[
            ConfusionMatrixEvaluator(
                predicted_from="labels",
                predicted_key="route",
                expected_from="metadata",
                expected_key="expected_route",
                title="Routing confusion matrix",
            )
        ],
    )
    sha, dirty = git_state()
    from agentic.observability.settings import ObservabilitySettings

    observability = ObservabilitySettings()
    metadata = RunMetadata(
        experiment_id=uuid4().hex,
        experiment_name=experiment_name or f"{suite_label}-{mode}",
        suite=suite_label,
        mode=mode,
        dataset=dataset,
        git_sha=sha,
        git_dirty=dirty,
        release=observability.LANGFUSE_RELEASE,
        environment=observability.LANGFUSE_TRACING_ENVIRONMENT,
        models=model_config,
        prompt_versions=prompt_versions(),
        graph_version=graph_version(),
        jev_config=jev,
        judge_config=judge_config,
        evaluator_versions=EVALUATOR_VERSIONS,
        started_at=contracts.now(),
        repeat=repeat,
        notes=notes,
    )
    started = perf_counter()
    report = await dataset_obj.evaluate(
        task, max_concurrency=concurrency, progress=False, repeat=repeat, task_name="graph_runtime"
    )
    metadata.finished_at = contracts.now()
    run = contracts.EvaluationRun(metadata=metadata, results=to_results(report, cases))
    run.analyses["pydantic_evals"] = [
        a.model_dump(mode="json") if hasattr(a, "model_dump") else getattr(a, "__dict__", str(a))
        for a in report.analyses
    ]
    run.analyses["wall_seconds"] = round(perf_counter() - started, 3)
    return run
