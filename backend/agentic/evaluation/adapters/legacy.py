"""Đưa các bộ eval có sẵn về hợp đồng thống nhất: cùng giao diện chạy, cùng báo cáo, cùng mã thoát.

| Bộ | Chạy được trong CI | Nguồn |
|---|---|---|
| daily-health | có (tổng hợp, seed cố định, không DB) | scripts/daily_health_backtest.py |
| rag | cần DB + embedding (trả phí) → --allow-paid | rag_suite.py (thay rag_eval retrieval) |
| jev | cần gateway Jev + review người → nhập kết quả | jev_eval.py (giữ split 100/200, chặn rò rỉ) |
| kg, memory, personalization, performance | cần model/backend/Neo4j → nhập kết quả | kg_eval, memory_eval, personalization_eval, system_benchmark |

Không bộ nào bị coi là đạt khi chưa chạy: thiếu phụ thuộc → `blocked` (mã 4) kèm lý do.
"""

import asyncio
import csv
import json
import sys
from pathlib import Path
from uuid import uuid4

from agentic.evaluation import contracts, reporting
from agentic.evaluation.contracts import (
    EXIT_CODES,
    CaseResult,
    EvaluationCase,
    EvaluationRun,
    EvaluationScore,
    RunMetadata,
)

EVALUATION = Path(__file__).parents[1]
BACKEND = EVALUATION.parents[1]
RUN_HINTS = {
    "kg": "python -m agentic.evaluation.kg_eval run --variants no_kg,kg --out <dir>  (agentic container)",
    "memory": "python -m agentic.evaluation.memory_eval run --modes off,on --out <dir>",
    "personalization": "python -m agentic.evaluation.personalization_eval --out <dir>",
    "performance": "python -m agentic.evaluation.system_benchmark parallel --out <dir>",
    "jev": "python -m agentic.evaluation.jev_eval execute --allow-live ... --out <prefix>",
}


def _metadata(suite, mode, dataset, **extra):
    from agentic.evaluation.runner import git_state
    from agentic.observability.settings import ObservabilitySettings

    sha, dirty = git_state()
    config = ObservabilitySettings()
    extra.setdefault("release", config.LANGFUSE_RELEASE)
    extra.setdefault("environment", config.LANGFUSE_TRACING_ENVIRONMENT)
    return RunMetadata(
        experiment_id=uuid4().hex,
        experiment_name=f"{suite}-{mode}",
        suite=suite,
        mode=mode,
        dataset=dataset,
        git_sha=sha,
        git_dirty=dirty,
        started_at=contracts.now(),
        finished_at=contracts.now(),
        **extra,
    )


def _finish(run, out, blockers=()):
    report = reporting.build_report(run, blockers=blockers)
    folder = reporting.write(run, report, out)
    print(reporting.markdown(report))
    print("saved", folder)
    return report.exit_code


def blocked(suite, reason, out):
    from agentic.evaluation.__main__ import blocked as write_blocked

    return write_blocked(suite, "import", reason, out)


# ------------------------------------------------------------------------------------------- daily health
def daily_health(out, seed=7):
    """Backtest tổng hợp có nhãn của engine readiness: chạy thật (tất định), không DB, không model."""
    # Nạp theo đường dẫn: tên package `scripts` trùng với agentic/scripts khi chạy từ thư mục agentic.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hercfit_daily_health_backtest", BACKEND / "scripts" / "daily_health_backtest.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    scenarios = module.run_scenarios(seed)
    rows = [
        {"scenario": name, **{k: v for k, v in data.items() if k != "description"}}
        for name, data in scenarios.items()
    ]
    dataset = contracts.dataset_info(
        "daily_health_scenarios",
        rows,
        version=f"seed-{seed}",
        path="scripts/daily_health_backtest.py",
    )
    results = []
    for name, data in scenarios.items():
        case = EvaluationCase(
            id=name,
            suite="daily_health",
            input={"seed": seed, "days": data.get("days")},
            reference={"description": data.get("description")},
            tags=["synthetic"],
        )
        scores = []
        for metric in (
            "false_alarm_rate",
            "strain_detection",
            "review_detection",
            "review_as_needs_review",
            "missing_as_insufficient",
            "normal_insufficient",
        ):
            if data.get(metric) is not None:
                scores.append(
                    EvaluationScore(
                        case_id=name,
                        name=metric,
                        value=float(data[metric]),
                        data_type="NUMERIC",
                        evaluator="daily_health_backtest",
                        evaluator_version="backtest-2026-11-08",
                    )
                )
        neutral = (data.get("notifications") or {}).get("needs_review_always_neutral")
        if neutral is not None:
            # Trạng thái cần xem lại không bao giờ được thông báo bằng giọng khen/ép tập: thuộc cổng an toàn cứng.
            scores.append(
                EvaluationScore(
                    case_id=name,
                    name="needs_review_neutral",
                    value=bool(neutral),
                    data_type="BOOLEAN",
                    passed=bool(neutral),
                    gate="hard_safety",
                    evaluator="daily_health_backtest",
                    evaluator_version="backtest-2026-11-08",
                )
            )
        per_week = (data.get("notifications") or {}).get("per_week")
        if per_week is not None:
            scores.append(
                EvaluationScore(
                    case_id=name,
                    name="notifications_per_week",
                    value=float(per_week),
                    data_type="NUMERIC",
                    gate="info",
                    evaluator="daily_health_backtest",
                    evaluator_version="backtest-2026-11-08",
                )
            )
        results.append(CaseResult(case=case, record=data, scores=scores))
    run = EvaluationRun(
        metadata=_metadata(
            "daily_health",
            "deterministic",
            dataset,
            notes=[
                "Dữ liệu TỔNG HỢP, nhãn do bộ sinh đặt: kiểm tra nhất quán, "
                "không phải kiểm định lâm sàng."
            ],
        ),
        results=results,
    )
    return _finish(run, out)


# ------------------------------------------------------------------------------------------- RAG
def rag(args):
    from agentic.evaluation import rag_suite

    if args.import_only:
        return rag_import(Path(args.import_only), args.out)
    if not args.allow_paid:
        return blocked(
            "rag", "retrieval calls the paid embedding/rerank provider; pass --allow-paid", args.out
        )
    cases, dataset = rag_suite.load_cases()
    codes = []
    for variant in args.variants or ["hybrid_rerank"]:
        run = asyncio.run(rag_suite.run_variant(variant, cases, dataset, answers=args.ragas))
        if args.ragas:
            path = Path(args.out) / f"ragas-input-{variant}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            print("ragas records:", rag_suite.export_ragas(run, path), "→", path)
        codes.append(_finish(run, args.out))
    return max(codes)


def rag_import(folder, out):
    """Nhập kết quả `rag_eval retrieval` cũ (cases.csv) vào hợp đồng."""
    from agentic.evaluation import rag_suite

    rows = list(csv.DictReader(open(folder / "cases.csv")))
    summary = (
        json.loads((folder / "summary.json").read_text())
        if (folder / "summary.json").exists()
        else {}
    )
    cases, dataset = rag_suite.load_cases()
    by_id = {c.id: c for c in cases}
    results = []
    for row in rows:
        case = by_id.get(row["id"])
        if case is None:
            continue
        scores = []
        for key in ("hit@1", "hit@3", "hit@5", "recall@5", "mrr@10", "ndcg@5", "chapter@3"):
            if row.get(key) not in (None, ""):
                scores.append(
                    EvaluationScore(
                        case_id=case.id,
                        name=key,
                        value=float(row[key]),
                        data_type="NUMERIC",
                        evaluator="rag_eval",
                        evaluator_version="rag_eval-legacy",
                    )
                )
        results.append(CaseResult(case=case, record=row, scores=scores))
    run = EvaluationRun(
        metadata=_metadata(
            "rag",
            "retrieval",
            dataset,
            rag_config=summary.get("options") or {},
            notes=[f"imported from {folder}"],
        ),
        results=results,
    )
    return _finish(run, out)


# ------------------------------------------------------------------------------------------- JEV
def jev(args):
    from agentic.evaluation import jev_eval

    cases = jev_eval.load_cases(args.split)  # tự chặn rò rỉ split theo scenario_id
    leak = split_leakage(jev_eval.load_cases("all"))
    dataset = contracts.dataset_info(
        "jev_cases",
        cases,
        version="2026-11",
        split=args.split,
        path="agentic/evaluation/datasets/jev_cases.jsonl",
    )
    if not args.import_only:
        return blocked(
            "jev",
            "live Jev runs need the gateway, a fixture and human reviews; run "
            f"`{RUN_HINTS['jev']}` then --import-only <prefix>",
            args.out,
        )
    prefix = Path(args.import_only)
    rows = contracts.load_jsonl(str(prefix) + ".runs.jsonl")
    reviews_path = Path(str(prefix) + ".reviews.jsonl")
    reviews = contracts.load_jsonl(reviews_path) if reviews_path.exists() else []
    result = jev_eval.report_rows(rows, reviews, cases=cases)
    blockers = list(dict.fromkeys(result.get("blockers") or [])) + leak
    run = EvaluationRun(
        metadata=_metadata(
            "jev",
            args.split,
            dataset,
            jev_config={"split": args.split, "modes": ["off", "enforce"]},
            notes=[
                "JEV_MODE=enforce không phải bằng chứng chất lượng: chỉ báo cáo khi "
                "có đủ review người, usage/giá và cặp off/enforce khớp."
            ],
        )
    )
    for mode, metrics in (result.get("metrics") or {}).items():
        for key, value in (metrics or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                run.aggregates[f"{mode}_{key}"] = value
    report = reporting.build_report(run, blockers=blockers)
    folder = reporting.write(run, report, args.out)
    print(reporting.markdown(report))
    print("saved", folder)
    return report.exit_code


def split_leakage(rows):
    """Rò rỉ calibration ↔ holdout: cùng scenario ở hai split, hoặc cùng tin nhắn (chuẩn hoá) ở hai split."""
    from domains.catalog.models.foods import normalize_food_text

    blockers = []
    by_message = {}
    for row in rows:
        key = normalize_food_text(row.get("message") or "")
        by_message.setdefault(key, set()).add(row.get("split"))
    if any(len(splits) > 1 for splits in by_message.values()):
        blockers.append("message_split_leakage")
    return blockers


# ------------------------------------------------------------------------------------------- nhập kết quả cũ
def import_legacy(suite, folder, out):
    folder = Path(folder)
    if suite == "performance":
        files = sorted(folder.glob("*.json"))
        data = {path.stem: json.loads(path.read_text()) for path in files}
        dataset = contracts.dataset_info(
            "system_benchmark", [data], version="imported", path=str(folder)
        )
        run = EvaluationRun(
            metadata=_metadata(suite, "offline_import", dataset, notes=[f"imported from {folder}"]),
            analyses={"raw": data},
        )
        return _finish(run, out)
    rows_path = folder / ("cases.jsonl" if (folder / "cases.jsonl").exists() else "rows.csv")
    if rows_path.suffix == ".jsonl":
        rows = contracts.load_jsonl(rows_path)
    else:
        rows = list(csv.DictReader(open(rows_path)))
    dataset = contracts.dataset_info(f"{suite}_cases", rows, version="imported", path=str(folder))
    results = []
    for index, row in enumerate(rows):
        case_id = str(row.get("id") or row.get("case") or row.get("case_id") or index)
        case = EvaluationCase(
            id=case_id,
            suite=suite,
            input={k: row[k] for k in ("variant", "mode") if k in row},
            tags=[str(row.get("variant") or row.get("mode") or "")],
        )
        scores = []
        for key, value in row.items():
            if key in {"ok", "pass", "passed", "personalize_ok", "topic_ok", "action_ok"}:
                truth = value in (True, "True", "true", "1", 1)
                scores.append(
                    EvaluationScore(
                        case_id=case_id,
                        name=f"{suite}_{key}",
                        value=truth,
                        data_type="BOOLEAN",
                        passed=truth,
                        evaluator=f"{suite}_eval",
                        evaluator_version="legacy",
                    )
                )
        results.append(CaseResult(case=case, record=dict(row), scores=scores))
    run = EvaluationRun(
        metadata=_metadata(suite, "offline_import", dataset, notes=[f"imported from {folder}"]),
        results=results,
    )
    return _finish(run, out)


def run_command(args):
    if args.command == "daily-health":
        return daily_health(args.out)
    if args.command == "rag":
        return rag(args)
    if args.command == "jev":
        return jev(args)
    if args.command == "performance" and not args.import_only:
        from agentic.evaluation import performance

        run = asyncio.run(performance.benchmark())
        return _finish(run, args.out)
    if args.import_only:
        return import_legacy(args.command, args.import_only, args.out)
    return blocked(
        args.command,
        f"needs live models/backend; run `{RUN_HINTS[args.command]}` then --import-only <dir>",
        args.out,
    )


def index(out):
    """eval:report — gộp mọi report.json trong thư mục --out thành bảng tổng hợp (JSON + Markdown)."""
    folder = Path(out)
    rows = []
    for path in sorted(folder.glob("*/report.json")):
        data = json.loads(path.read_text())
        meta = data.get("metadata") or {}
        rows.append(
            {
                "run": path.parent.name,
                "suite": meta.get("suite") or data.get("suite"),
                "mode": meta.get("mode") or data.get("mode"),
                "status": data.get("status"),
                "exit_code": data.get("exit_code"),
                "git_sha": (meta.get("git_sha") or "")[:12],
                "dataset": (meta.get("dataset") or {}).get("fingerprint", "")[:12],
                "failed_gates": [g["name"] for g in data.get("gates") or [] if not g.get("passed")],
                "blockers": data.get("blockers") or [],
            }
        )
    latest = {}
    for row in rows:
        latest[(row["suite"], row["mode"])] = row
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.json").write_text(
        json.dumps({"runs": rows, "latest": list(latest.values())}, indent=2) + "\n"
    )
    lines = [
        "| Bộ | Chế độ | Kết quả | Mã | Commit | Dataset | Cổng trượt / bị chặn |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in latest.values():
        lines.append(
            f"| {row['suite']} | {row['mode']} | {row['status']} | {row['exit_code']} | {row['git_sha']} | "
            f"{row['dataset']} | {', '.join(row['failed_gates'] + row['blockers'])} |"
        )
    (folder / "index.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    worst = max(
        (row["exit_code"] or 0 for row in latest.values() if row["status"] != "blocked"), default=0
    )
    return worst if worst else (EXIT_CODES["pass"])
