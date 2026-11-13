"""E5 — nguồn ngữ cảnh cá nhân: câu trả lời cho câu hỏi về dữ liệu của chính người dùng, theo từng cấu hình nguồn.

    python -m evaluation.context_sources_eval --dry-run
    python -m evaluation.context_sources_eval --mode deterministic --out /tmp/e5
    python -m evaluation.context_sources_eval --mode live --allow-paid --repeat 3 --out eval_results/e5   # tốn phí

Chạy từ backend/ với PYTHONPATH=../tests (như các bộ eval khác).

Ca: datasets/context_cases.jsonl — câu hỏi có đáp án kỳ vọng trên người dùng tổng hợp của kg_eval (`kg_eval seed`).
Cấu hình nguồn đặt qua settings CONTEXT_SOURCES (personal_context.sources, L4.4); kg_facts tắt ở cả ba cấu hình.

* deterministic: model kịch bản (router trả quyết định của ca), backend giả có thẻ hồ sơ, dịch vụ context graph giả.
  Kiểm dây nối: mỗi cấu hình chỉ chạm đúng các nguồn của nó. Không gọi mạng, không tốn phí; độ đúng câu trả lời không
  có nghĩa ở chế độ này.
* live: model thật, backend thật với người dùng eval tổng hợp (token ký như kg_eval), context graph trên Neo4j, store
  và checkpoint trong bộ nhớ (không ghi database của agent). Chấm câu trả lời bằng chuỗi kỳ vọng. Cần --allow-paid.
"""

import argparse
import asyncio
import csv
import json
import statistics
import subprocess
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

CASES = Path(__file__).parent / "datasets" / "context_cases.jsonl"
CONFIGS = {
    "card": ["card"],
    "card+backend_reads": ["card", "backend_reads"],
    "card+backend_reads+context_graph": ["card", "backend_reads", "context_graph"],
}
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
# Ước lượng cho --dry-run: số lời gọi model mỗi ca (router, tool, câu trả lời, Context Agent) và token mỗi lời gọi.
CALLS_PER_CASE = {"card": 3, "card+backend_reads": 3, "card+backend_reads+context_graph": 4}
INPUT_TOKENS_PER_CALL, OUTPUT_TOKENS_PER_CALL = 6000, 400
CARD = {"today": None, "profile": {"age": 29, "sex": "MALE"}, "body": {"weight_kg": 71.8, "height_cm": 172},
        "athlete": {}, "running": {}, "training_4w": {}, "missing": [],
        "inventory": {"trainings_60d": 8, "body_metrics": 3, "meals_14d": 10}}


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", str(text).lower().replace("đ", "d"))
                   if unicodedata.category(c) != "Mn")


def anchors_from(day0: date):
    marks = {}
    for k in range(32):
        day = day0 - timedelta(days=k)
        marks[f"s{k}"], marks[f"s{k}_iso"], marks[f"s{k}_month"] = day.strftime("%d/%m"), day.isoformat(), day.month
    return marks


def load_cases(marks, only=()):
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    cases = [c for c in cases if not only or c["id"] in only or c["group"] in only]
    for case in cases:
        case["message"] = case["message"].format(**marks)
        case["expect"] = [[k.format(**marks) for k in group] for group in case["expect"]]
    return cases


def recall(expect, reply):
    text = normalize(reply)
    return all(any(normalize(k) in text for k in group) for group in expect)


def git_state():
    root = Path(__file__).parents[2]
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip())
    return sha, dirty


class StubGraph:
    """Dịch vụ context graph giả của chế độ tất định: chỉ ghi nhận lần đọc sự kiện KG."""

    def __init__(self):
        self.retrieved = 0

    async def retrieve(self, **kwargs):
        self.retrieved += 1
        return SimpleNamespace(model_dump=lambda mode=None: {"status": "empty", "facts": []})


async def run_case(case, sources, mode, deps):
    from agentic.agents.state import initial_state
    from agentic.agents.workflow import build_workflow
    from agentic.core.context import RequestContext, request_context
    from agentic.knowledge_graph.context import pipeline
    from agentic.knowledge_graph.context.graph import ContextGraph
    from evaluation.adapters.fixtures import EvalBackend, EvalStore

    settings = deps.settings.model_copy(update={"CONTEXT_SOURCES": sources})
    built = []
    if mode == "deterministic":
        from evaluation.adapters.graph_runtime import ScriptedModels

        decision = {"action": "answer", "next_agent": "orchestrator", "instruction": "Trả lời.", **case["decision"]}
        models, backend, graph = ScriptedModels({"decision": [decision]}), EvalBackend(card=CARD), StubGraph()
        token, user = "eval-token:u-e5", "u-e5"

        async def build(service, models_, **kwargs):
            built.append(kwargs["question"])
            return ContextGraph(status="blocked")

        original, pipeline.build = pipeline.build, build
    else:
        models, backend, graph, token, user = deps.models, deps.backend, deps.graph, deps.token, deps.user
        original = None
    workflow = build_workflow(models, EvalStore(), MemorySaver(), deps.tavily, settings, graph_context=graph)
    marker = request_context.set(RequestContext(user, token, backend))
    started = perf_counter()
    try:
        state = await workflow.ainvoke(
            initial_state(run_id=f"e5-{case['id']}", user_id=user, session_id="e5", mode=None,
                          messages=[HumanMessage(content=case["message"])]),
            {"configurable": {"thread_id": f"e5-{case['id']}-{'-'.join(sources)}-{perf_counter()}"},
             "recursion_limit": settings.MAX_GRAPH_STEPS})
        error = None
    except Exception as exc:  # noqa: BLE001 - lỗi của một ca được ghi lại, không dừng cả lần chạy
        state, error = {}, type(exc).__name__
    finally:
        request_context.reset(marker)
        if original is not None:
            pipeline.build = original
    elapsed = (perf_counter() - started) * 1000
    telemetry = state.get("telemetry") or {}
    reply = state.get("reply") or ""
    used = {}
    if mode == "deterministic":
        names = [call["name"] for call in backend.calls]
        used = {"card": any(n.endswith("/assistant/context") for n in names), "context_graph": bool(built),
                "kg_facts": graph.retrieved > 0}
    return {"id": case["id"], "group": case["group"], "config": "+".join(sources), "status": state.get("status"),
            "error": error, "recall": recall(case["expect"], reply), "ms": round(elapsed, 1),
            "llm_calls": telemetry.get("llm_calls", 0), "input_tokens": telemetry.get("input_tokens", 0),
            "output_tokens": telemetry.get("output_tokens", 0), **{f"used_{k}": v for k, v in used.items()},
            "reply": reply[:500]}


def summarize(rows, repeat):
    lines = ["| cấu hình | n | độ đúng (TB ± độ lệch giữa các lần) | p50 ms | p95 ms | LLM calls TB | in tok TB | out tok TB "
             "| lỗi |", "|---|---|---|---|---|---|---|---|---|"]
    for config in dict.fromkeys(r["config"] for r in rows):
        sel = [r for r in rows if r["config"] == config]
        per_repeat = [statistics.mean(r["recall"] for r in sel if r["repeat"] == i) for i in range(repeat)]
        spread = f" ± {statistics.stdev(per_repeat):.3f}" if len(per_repeat) > 1 else ""
        ms = sorted(r["ms"] for r in sel)
        lines.append(f"| {config} | {len(sel) // repeat} | {statistics.mean(per_repeat):.3f}{spread} | "
                     f"{ms[len(ms) // 2]} | {ms[min(len(ms) - 1, int(.95 * len(ms)))]} | "
                     f"{statistics.mean(r['llm_calls'] for r in sel):.2f} | "
                     f"{statistics.mean(r['input_tokens'] for r in sel):.0f} | "
                     f"{statistics.mean(r['output_tokens'] for r in sel):.0f} | {sum(1 for r in sel if r['error'])} |")
    return lines


async def main(args):
    configs = args.configs or list(CONFIGS)
    if args.mode == "live" and not args.allow_paid:
        print("live mode calls paid models: pass --allow-paid", file=sys.stderr)
        return 4
    if args.dry_run:
        cases = load_cases(anchors_from(datetime.now(TZ).date()), args.cases or ())
        calls = sum(CALLS_PER_CASE[c] for c in configs) * len(cases) * args.repeat
        print(f"E5 dry run: {len(cases)} ca × {len(configs)} cấu hình × {args.repeat} lần = "
              f"{len(cases) * len(configs) * args.repeat} lượt; ước tính {calls} lời gọi model, "
              f"~{calls * INPUT_TOKENS_PER_CALL / 1e6:.2f}M token vào, ~{calls * OUTPUT_TOKENS_PER_CALL / 1e6:.2f}M token ra")
        for config in configs:
            print(f"- {config}: CONTEXT_SOURCES={CONFIGS[config]}")
        return 0
    from evaluation.adapters.graph_runtime import eval_settings, prompt_versions

    deps = SimpleNamespace(settings=eval_settings(), tavily=None)
    if args.mode == "live":
        from agentic.core.app.config import agent_settings
        from agentic.core.llm import Models
        from agentic.knowledge_graph.service import GraphContextService
        from agentic.observability.telemetry import MeasuredModels
        from agentic.tools.integrations.backend_client import BackendClient
        from agentic.tools.integrations.tavily import TavilyClient
        from evaluation.kg_eval import EVAL_USER, seed_anchors, token

        secret = agent_settings.AGENT_SERVICE_SECRET.get_secret_value() if agent_settings.AGENT_SERVICE_SECRET else None
        deps = SimpleNamespace(
            settings=agent_settings, models=MeasuredModels(Models(agent_settings)),
            backend=BackendClient(agent_settings.BACKEND_BASE_URL, agent_settings.BACKEND_TIMEOUT_SECONDS,
                                  **({"service_secret": secret} if secret else {})),
            graph=GraphContextService(agent_settings, None), token=token(), user=str(EVAL_USER),
            tavily=TavilyClient(agent_settings.TAVILY_API_KEY.get_secret_value() if agent_settings.TAVILY_API_KEY else ""))
        marks = await seed_anchors()
        models_config = {role: str(getattr(agent_settings, f"{role.upper()}_MODEL", None) or agent_settings.DEFAULT_MODEL)
                         for role in ("decision", "tool", "response", "research")}
    else:
        marks = anchors_from(datetime.now(TZ).date())
        models_config = {"all_roles": "scripted"}
    cases = load_cases(marks, args.cases or ())
    sha, dirty = git_state()
    rows = []
    try:
        for index in range(args.repeat):
            for config in configs:
                for case in cases:
                    row = await run_case(case, CONFIGS[config], args.mode, deps)
                    rows.append({**row, "repeat": index})
                    print(f"[{index}] {config:<34} {case['id']:<22} recall={row['recall']!s:<5} {row['ms']:8.1f}ms "
                          f"{row['error'] or ''}", flush=True)
    finally:
        if args.mode == "live":
            await deps.backend.close()
            await deps.graph.close()
            await deps.tavily.close()
    header = [f"# E5 nguồn ngữ cảnh · {args.mode}", "",
              f"- Commit: `{sha[:12]}`{' (dirty)' if dirty else ''}", f"- Models: {json.dumps(models_config)}",
              f"- Prompt: {json.dumps(prompt_versions(), ensure_ascii=False)}",
              f"- Ca: {len(cases)} (`{CASES.name}`) · cấu hình: {len(configs)} · lặp: {args.repeat}", ""]
    lines = header + summarize(rows, args.repeat)
    if args.mode == "deterministic":
        lines += ["", "Dây nối (chế độ tất định): nguồn được chạm theo cấu hình", "",
                  "| cấu hình | thẻ hồ sơ | context graph | sự kiện KG |", "|---|---|---|---|"]
        for config in configs:
            sel = [r for r in rows if r["config"] == "+".join(CONFIGS[config])]
            lines.append(f"| {config} | {sum(r['used_card'] for r in sel)}/{len(sel)} | "
                         f"{sum(r['used_context_graph'] for r in sel)}/{len(sel)} | "
                         f"{sum(r['used_kg_facts'] for r in sel)}/{len(sel)} |")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "rows.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def cli(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evaluation.context_sources_eval", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["deterministic", "live"], default="deterministic")
    parser.add_argument("--configs", nargs="+", choices=list(CONFIGS))
    parser.add_argument("--cases", nargs="+", help="id hoặc nhóm ca")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="chỉ in kế hoạch và ước lượng chi phí")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--out", default="eval_results/e5")
    return asyncio.run(main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(cli())
