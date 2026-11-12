"""CLI thống nhất cho mọi bộ eval (chạy từ thư mục backend/, với PYTHONPATH=../tests; xem tests/Makefile):

    python -m evaluation agent [--mode live --allow-paid]
    python -m evaluation safety [--mode live --allow-paid]
    python -m evaluation rag [--variants ...]      # cần DB + embedding provider
    python -m evaluation kg | jev | memory | personalization | daily-health | performance
    python -m evaluation full [--live --allow-paid]
    python -m evaluation report [--out eval_results/quality]
    python -m evaluation langfuse-sync <report.json>

Mã thoát: 0 đạt · 1 trượt cổng chất lượng/hồi quy · 2 trượt cổng an toàn cứng · 3 lỗi runner/hạ tầng · 4 bị chặn
(thiếu phụ thuộc ngoài: database, khoá model, credit chưa được phép). Mỗi lần chạy ghi run.json, report.json và
report.md vào thư mục --out.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from evaluation import reporting
from evaluation.contracts import EXIT_CODES

BACKEND = Path(__file__).parents[2] / "backend"
DEFAULT_OUT = "eval_results/quality"


def blocked_live(args):
    """Chế độ live gọi model thật (tốn credit): cần khoá và cờ --allow-paid tường minh."""
    if not getattr(args, "allow_paid", False):
        return "live mode calls paid models; pass --allow-paid to authorise the spend"
    try:
        from agentic.core.app.config import agent_settings

        if not agent_settings.model_api_key:
            return "no model API key configured for the agent"
    except Exception as exc:  # noqa: BLE001
        return f"agent settings unavailable: {type(exc).__name__}"
    return None


async def agent_like(args, *, suite_label, tags=None):
    from evaluation import runner

    if args.mode == "live":
        reason = blocked_live(args)
        if reason:
            return blocked(suite_label, args.mode, reason, args.out)
    run = await runner.run_agent_suite(
        args.mode,
        tags=tags,
        ids=args.cases,
        repeat=args.repeat,
        concurrency=args.concurrency,
        judge=args.judge,
        trace=args.trace,
        suite_label=suite_label,
    )
    report = reporting.build_report(run)
    folder = reporting.write(run, report, args.out)
    if args.update_baseline:
        if report.status == "pass" and (not run.metadata.git_dirty or args.allow_dirty):
            print("baseline updated:", reporting.save_baseline(run))
        else:
            print(
                "baseline NOT updated: requires a passing run on a clean commit (--allow-dirty to override; "
                "the baseline then records git_dirty=true)",
                file=sys.stderr,
            )
    if args.langfuse:
        from evaluation import langfuse_sync

        print(json.dumps(langfuse_sync.sync(run, report, folder=folder), ensure_ascii=False))
    print(reporting.markdown(report))
    print("saved", folder)
    return report.exit_code


def blocked(suite, mode, reason, out):
    folder = Path(out) / f"blocked-{suite}-{mode}"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "suite": suite,
        "mode": mode,
        "status": "blocked",
        "exit_code": EXIT_CODES["blocked"],
        "blockers": [reason],
    }
    (folder / "report.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(f"BLOCKED {suite}:{mode}: {reason}", file=sys.stderr)
    return EXIT_CODES["blocked"]


def legacy(args):
    from evaluation.adapters import legacy as adapter

    return adapter.run_command(args)


def full(args):
    """Bộ đầy đủ: tất định luôn chạy; live chỉ khi --live --allow-paid; bộ cần hạ tầng báo BLOCKED nếu thiếu."""
    codes = {}
    for suite in ("agent", "safety"):
        ns = argparse.Namespace(
            **{**vars(args), "mode": "deterministic", "cases": None, "update_baseline": False}
        )
        codes[f"{suite}:deterministic"] = asyncio.run(
            agent_like(ns, suite_label=suite, tags=None if suite == "agent" else SAFETY_TAGS)
        )
        if args.live:
            ns.mode = "live"
            codes[f"{suite}:live"] = asyncio.run(
                agent_like(ns, suite_label=suite, tags=None if suite == "agent" else SAFETY_TAGS)
            )
    for name in ("rag", "jev", "daily-health", "performance"):
        codes[name] = legacy(
            argparse.Namespace(**{**vars(args), "command": name, "import_only": False})
        )
    print(json.dumps(codes, indent=2))
    order = [EXIT_CODES[k] for k in ("safety_fail", "error", "fail", "blocked")]
    worst = next((code for code in order if code in codes.values()), 0)
    return worst


SAFETY_TAGS = ["safety", "authorization", "injection", "confirmation", "tool_policy"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m evaluation",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("agent", "safety"):
        p = sub.add_parser(name)
        p.add_argument("--mode", choices=["deterministic", "live"], default="deterministic")
        p.add_argument("--cases", nargs="+")
        p.add_argument("--repeat", type=int, default=1)
        p.add_argument("--concurrency", type=int, default=4)
        p.add_argument(
            "--judge", action="store_true", help="LLM-as-judge (cần JUDGE_* và --allow-paid)"
        )
        p.add_argument(
            "--trace",
            action="store_true",
            help="gắn mỗi ca vào một trace Langfuse (khi tracing bật)",
        )
        p.add_argument(
            "--langfuse", action="store_true", help="đẩy điểm và experiment lên Langfuse"
        )
        p.add_argument("--allow-paid", action="store_true")
        p.add_argument("--update-baseline", action="store_true")
        p.add_argument("--allow-dirty", action="store_true")
        p.add_argument("--out", default=DEFAULT_OUT)
    for name in ("rag", "kg", "jev", "memory", "personalization", "daily-health", "performance"):
        p = sub.add_parser(name)
        p.add_argument("--out", default=DEFAULT_OUT)
        p.add_argument(
            "--import-only", help="chỉ quy kết quả đã có (thư mục/file) về hợp đồng, không chạy lại"
        )
        p.add_argument("--allow-paid", action="store_true")
        p.add_argument("--variants", nargs="+")
        p.add_argument("--split", choices=["calibration", "holdout"], default="holdout")
        p.add_argument(
            "--ragas", action="store_true", help="xuất bản ghi cho bộ chấm Ragas (venv riêng)"
        )
    p = sub.add_parser("full")
    p.add_argument("--live", action="store_true")
    p.add_argument("--allow-paid", action="store_true")
    p.add_argument("--judge", action="store_true")
    p.add_argument("--trace", action="store_true")
    p.add_argument("--langfuse", action="store_true")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--out", default=DEFAULT_OUT)
    p = sub.add_parser("report")
    p.add_argument("--out", default=DEFAULT_OUT)
    p = sub.add_parser("langfuse-sync")
    p.add_argument("run", help="đường dẫn run.json")
    p.add_argument("--force", action="store_true", help="đồng bộ lại dù đã có .langfuse-synced")
    p = sub.add_parser(
        "regression-candidates", help="trace điểm thấp → hàng đợi review (không chép nội dung)"
    )
    p.add_argument("--max-value", type=float, default=0.0)
    p.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    os.chdir(BACKEND)
    if args.command == "agent":
        return asyncio.run(agent_like(args, suite_label="agent"))
    if args.command == "safety":
        return asyncio.run(agent_like(args, suite_label="safety", tags=SAFETY_TAGS))
    if args.command == "full":
        return full(args)
    if args.command == "report":
        from evaluation.adapters.legacy import index

        return index(args.out)
    if args.command == "langfuse-sync":
        from evaluation import langfuse_sync
        from evaluation.contracts import EvaluationRun

        run = EvaluationRun.model_validate_json(Path(args.run).read_text())
        report = reporting.build_report(run)
        result = langfuse_sync.sync(run, report, folder=Path(args.run).parent, force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return EXIT_CODES["blocked"] if result["status"] == "blocked" else 0
    if args.command == "regression-candidates":
        from evaluation import langfuse_sync

        result = langfuse_sync.regression_candidates(max_value=args.max_value)
        path = Path(args.out) / "regression_candidates.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(c) + "\n" for c in result["candidates"]))
        print(
            json.dumps({k: v for k, v in result.items() if k != "candidates"}, indent=2), "→", path
        )
        return EXIT_CODES["blocked"] if result["status"] == "blocked" else 0
    return legacy(args)


if __name__ == "__main__":
    sys.exit(main())
