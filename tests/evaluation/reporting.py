"""Tổng hợp, cổng chất lượng, so sánh baseline và báo cáo máy-đọc/người-đọc cho mọi bộ eval.

Thứ tự quyết định (điểm ngữ nghĩa cao không bù được vi phạm an toàn):
1. Cổng an toàn cứng: bất kỳ điểm `hard_safety` nào trượt → `safety_fail` (mã thoát 2).
2. Cổng chất lượng: số đo dưới ngưỡng tuyệt đối → `fail` (1).
3. Cổng hồi quy: giảm quá `max_drop` so với baseline cùng dấu vân tay dataset → `fail` (1).
4. Ca lỗi hạ tầng (không phải lỗi agent) → `error` (3); phụ thuộc ngoài thiếu → `blocked` (4).
"""

import json
from collections import defaultdict
from pathlib import Path

from evaluation import scoring
from evaluation.contracts import EXIT_CODES, EvaluationReport, EvaluationRun, GateResult

EVALUATION = Path(__file__).parent
GATES = EVALUATION / "quality_gates.json"
BASELINES = EVALUATION / "baselines"


def aggregate(run: EvaluationRun):
    """Tỷ lệ/trung bình theo điểm, phân loại định tuyến, độ trễ và token trên các ca có nhãn tương ứng."""
    values = defaultdict(list)
    hard_failures = 0
    case_safety = defaultdict(list)
    for result in run.results:
        for score in result.scores:
            if score.data_type == "BOOLEAN":
                values[score.name].append(bool(score.value))
            elif score.data_type == "NUMERIC" and score.value is not None:
                values[score.name].append(float(score.value))
            if score.gate == "hard_safety":
                case_safety[result.case.id].append(bool(score.value))
                hard_failures += not score.value
    aggregates = {}
    for name, items in sorted(values.items()):
        aggregates[name] = round(sum(items) / len(items), 4) if items else None
    aggregates["safety_pass"] = (
        scoring.rate(all(v) for v in case_safety.values()) if case_safety else None
    )
    aggregates["hard_safety_violations"] = hard_failures
    aggregates["cases"] = len({r.case.id for r in run.results})
    aggregates["case_runs"] = len(run.results)
    aggregates["infrastructure_errors"] = sum(
        1 for r in run.results if r.error and r.error.category in {"infrastructure", "evaluator"}
    )
    records = [r.record for r in run.results if r.record]
    pairs = [
        ((r.case.reference.get("route") or [None])[0], r.record.get("route"))
        for r in run.results
        if r.case.reference.get("route") and r.record
    ]
    analyses = {}
    if pairs:
        # Ca chấp nhận nhiều route: dự đoán thuộc tập chấp nhận được tính là đúng nhãn kỳ vọng đầu tiên.
        normalized = [
            (expected, expected if predicted in r.case.reference["route"] else str(predicted))
            for (expected, predicted), r in zip(
                pairs, [x for x in run.results if x.case.reference.get("route") and x.record]
            )
        ]
        summary = scoring.classification_summary([({e}, {p}) for e, p in normalized])
        aggregates["routing_macro_f1"] = summary["macro_f1"]
        aggregates["routing_macro_precision"] = summary["macro_precision"]
        aggregates["routing_macro_recall"] = summary["macro_recall"]
        analyses["routing"] = {**summary, "confusion_matrix": scoring.confusion_matrix(normalized)}
    multi = [
        (set(r.case.reference["agents"]), set(r.record.get("selected_agents") or []))
        for r in run.results
        if r.case.reference.get("agents") is not None and r.record
    ]
    if multi:
        agents = scoring.classification_summary(multi)
        aggregates["agent_selection_macro_f1"] = agents["macro_f1"]
        analyses["agent_selection"] = agents
    aggregates.update(
        scoring.latency_summary(
            [r.get("latency_ms") for r in records] or [r.duration_ms for r in run.results]
        )
    )
    usage = scoring.usage_summary([r.get("usage") or {} for r in records])
    aggregates.update({f"usage_{k}": v for k, v in usage.items() if k != "cost_status"})
    analyses["usage_cost_status"] = usage["cost_status"]
    run.aggregates, run.analyses = aggregates, {**run.analyses, **analyses}
    return aggregates


def gate_config(suite, mode, path=GATES):
    config = json.loads(Path(path).read_text())
    return config["suites"].get(f"{suite}:{mode}") or config["suites"].get(suite) or {}


def baseline_path(suite, mode):
    return BASELINES / f"{suite}-{mode}.json"


def compare(aggregates, dataset_fingerprint, baseline, metrics):
    """So với baseline: chỉ so khi dataset trùng dấu vân tay (dataset đổi thì baseline không còn so sánh được)."""
    if not baseline:
        return {"status": "missing", "explanation": "No committed baseline for this suite/mode"}
    if baseline.get("dataset_fingerprint") != dataset_fingerprint:
        return {
            "status": "not_comparable",
            "explanation": "Dataset fingerprint differs from baseline; re-baseline "
            "with --update-baseline after review",
            "baseline_fingerprint": baseline.get("dataset_fingerprint"),
        }
    deltas = {}
    for metric in metrics:
        before, after = baseline["aggregates"].get(metric), aggregates.get(metric)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            deltas[metric] = {
                "baseline": before,
                "current": after,
                "delta": round(after - before, 4),
            }
    return {"status": "compared", "baseline_git_sha": baseline.get("git_sha"), "deltas": deltas}


def evaluate_gates(run: EvaluationRun, config, baseline=None):
    gates = []
    aggregates = run.aggregates
    violations = [
        (r.case.id, s.name, s.explanation)
        for r in run.results
        for s in r.scores
        if s.gate == "hard_safety" and not s.value
    ]
    hard = config.get("hard_safety", {"max_violations": 0})
    gates.append(
        GateResult(
            name="hard_safety",
            kind="hard_safety",
            metric="hard_safety_violations",
            threshold=hard.get("max_violations", 0),
            actual=len(violations),
            passed=len(violations) <= hard.get("max_violations", 0),
            justification=hard.get("justification"),
            explanation="; ".join(f"{c}:{n} ({e})" for c, n, e in violations[:10]) or None,
        )
    )
    for metric, rule in (config.get("quality") or {}).items():
        actual = aggregates.get(metric)
        threshold = rule.get("min")
        if actual is None:
            # Không có ca nào mang nhãn cho số đo này: báo rõ thay vì coi là đạt.
            gates.append(
                GateResult(
                    name=f"quality:{metric}",
                    kind="quality",
                    metric=metric,
                    threshold=threshold,
                    actual=None,
                    passed=not rule.get("required", False),
                    justification=rule.get("justification"),
                    explanation="no labelled cases",
                )
            )
            continue
        passed = actual >= threshold if rule.get("min") is not None else actual <= rule["max"]
        gates.append(
            GateResult(
                name=f"quality:{metric}",
                kind="quality",
                metric=metric,
                threshold=threshold if threshold is not None else rule.get("max"),
                actual=actual,
                passed=passed,
                justification=rule.get("justification"),
            )
        )
    regression = config.get("regression") or {}
    comparison = compare(
        aggregates, run.metadata.dataset.fingerprint, baseline, regression.get("metrics") or []
    )
    if comparison["status"] == "compared":
        for metric, delta in comparison["deltas"].items():
            drop = -delta["delta"]
            gates.append(
                GateResult(
                    name=f"regression:{metric}",
                    kind="regression",
                    metric=metric,
                    threshold=regression.get("max_drop", 0.0),
                    actual=round(drop, 4),
                    passed=drop <= regression.get("max_drop", 0.0) + 1e-9,
                    justification=regression.get("justification"),
                    explanation=f"baseline {delta['baseline']} → {delta['current']}",
                )
            )
    return gates, comparison


def decide(gates, run, blockers=()):
    if blockers:
        return "blocked"
    if any(not g.passed for g in gates if g.kind == "hard_safety"):
        return "safety_fail"
    if any(not g.passed for g in gates):
        return "fail"
    if run.aggregates.get("infrastructure_errors"):
        return "error"
    return "pass"


def build_report(run: EvaluationRun, *, gates_path=GATES, baseline=None, blockers=()):
    aggregate(run)
    config = gate_config(run.metadata.suite, run.metadata.mode, gates_path)
    if baseline is None:
        path = baseline_path(run.metadata.suite, run.metadata.mode)
        baseline = json.loads(path.read_text()) if path.exists() else None
    gates, comparison = evaluate_gates(run, config, baseline)
    status = decide(gates, run, blockers)
    failures = [
        {
            "case": r.case.id,
            "repeat": r.repeat_index,
            "severity": r.case.severity,
            "failed": [s.name for s in r.scores if s.passed is False],
            "error": r.error.model_dump() if r.error else None,
        }
        for r in run.results
        if any(s.passed is False for s in r.scores) or r.error
    ]
    return EvaluationReport(
        metadata=run.metadata,
        status=status,
        exit_code=EXIT_CODES[status],
        aggregates=run.aggregates,
        analyses=run.analyses,
        gates=gates,
        baseline=comparison,
        failures=failures,
        blockers=list(blockers),
    )


def markdown(report: EvaluationReport):
    meta = report.metadata
    lines = [
        f"# Eval `{meta.suite}` · {meta.mode} · **{report.status.upper()}** (exit {report.exit_code})",
        "",
        f"- Experiment: `{meta.experiment_name}` (`{meta.experiment_id}`)",
        f"- Dataset: `{meta.dataset.name}` v{meta.dataset.version}, {meta.dataset.case_count} ca, "
        f"fingerprint `{meta.dataset.fingerprint[:12]}`",
        f"- Commit: `{(meta.git_sha or 'unknown')[:12]}`{' (dirty)' if meta.git_dirty else ''} · release "
        f"`{meta.release}` · env `{meta.environment}` · graph `{meta.graph_version}`",
        f"- Models: {json.dumps(meta.models, ensure_ascii=False)}",
        f"- Evaluators: {json.dumps(meta.evaluator_versions)}",
        "",
        "## Cổng",
        "",
        "| Cổng | Loại | Ngưỡng | Thực tế | Kết quả | Căn cứ |",
        "|---|---|---|---|---|---|",
    ]
    for gate in report.gates:
        lines.append(
            f"| {gate.name} | {gate.kind} | {gate.threshold} | {gate.actual} | "
            f"{'PASS' if gate.passed else 'FAIL'} | {gate.justification or gate.explanation or ''} |"
        )
    lines += ["", "## Số đo", "", "| Số đo | Giá trị |", "|---|---|"]
    for key, value in report.aggregates.items():
        lines.append(f"| {key} | {value} |")
    if report.baseline:
        lines += ["", f"## Baseline: {report.baseline.get('status')}", ""]
        for metric, delta in (report.baseline.get("deltas") or {}).items():
            lines.append(
                f"- {metric}: {delta['baseline']} → {delta['current']} ({delta['delta']:+})"
            )
        if report.baseline.get("explanation"):
            lines.append(f"- {report.baseline['explanation']}")
    routing = report.analyses.get("routing")
    if routing:
        matrix = routing["confusion_matrix"]
        lines += [
            "",
            "## Ma trận nhầm định tuyến (hàng = kỳ vọng, cột = dự đoán)",
            "",
            "| | " + " | ".join(matrix["labels"]) + " |",
            "|---|" + "---|" * len(matrix["labels"]),
        ]
        for label, row in zip(matrix["labels"], matrix["matrix"]):
            lines.append(f"| {label} | " + " | ".join(str(v) for v in row) + " |")
    if report.failures:
        lines += ["", "## Ca trượt", ""]
        for failure in report.failures:
            lines.append(
                f"- `{failure['case']}` ({failure['severity']}): {', '.join(failure['failed'])}"
                + (f" — lỗi {failure['error']['code']}" if failure.get("error") else "")
            )
    if report.blockers:
        lines += ["", "## Bị chặn", "", *[f"- {b}" for b in report.blockers]]
    if meta.notes:
        lines += ["", "## Ghi chú", "", *[f"- {n}" for n in meta.notes]]
    return "\n".join(lines) + "\n"


def write(run: EvaluationRun, report: EvaluationReport, out):
    folder = (
        Path(out)
        / f"{run.metadata.started_at:%Y%m%d-%H%M%S}-{run.metadata.suite}-{run.metadata.mode}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(run.model_dump_json(indent=2))
    (folder / "report.json").write_text(report.model_dump_json(indent=2))
    (folder / "report.md").write_text(markdown(report))
    return folder


def save_baseline(run: EvaluationRun, path=None):
    path = Path(path or baseline_path(run.metadata.suite, run.metadata.mode))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "suite": run.metadata.suite,
                "mode": run.metadata.mode,
                "git_sha": run.metadata.git_sha,
                "git_dirty": run.metadata.git_dirty,
                "dataset_fingerprint": run.metadata.dataset.fingerprint,
                "dataset_version": run.metadata.dataset.version,
                "created_at": run.metadata.started_at.isoformat(),
                "aggregates": run.aggregates,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return path
