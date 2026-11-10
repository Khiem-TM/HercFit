"""Chạy graph LangGraph thật của HercFit (cùng `build_workflow`, cùng agent, luật code, cổng HITL) cho một ca eval
rồi quy kết quả về `AgentExecutionRecord`.

Hai chế độ:
* `deterministic`: model theo kịch bản của ca (không gọi mạng, không tốn credit) — kiểm tra hồi quy phần do code sở
  hữu: luật định tuyến, chính sách tool, cổng xác nhận, ghi sau phê duyệt, cô lập người dùng, chặn an toàn.
* `live`: model thật theo cấu hình agent (cần khoá nhà cung cấp, tốn credit) — đo định tuyến/tool của model.

Cả hai dùng store và backend cô lập (`fixtures.py`); không có đường nào tới database hay backend production. Ở tầng
này không có lớp HTTP/session của Runtime (cần PostgreSQL); kết cục SSE được kiểm tra riêng ở test chat_router.
"""

import hashlib
import re
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agentic.core import roster
from agentic.core.app.config import AgentSettings
from agentic.core.context import RequestContext, request_context
from agentic.evaluation.adapters.fixtures import EvalBackend, EvalStore, token_for
from agentic.evaluation.contracts import (
    AgentExecutionRecord,
    ErrorRecord,
    TokenUsage,
    ToolExecutionRecord,
)
from agentic.observability import graph_config
from agentic.observability.outcomes import classify
from agentic.services import mode as modes
from agentic.tools.registry import REGISTRY

AGENTIC = Path(__file__).parents[2]
AGENT_NODES = {*roster.SPECIALIST_DOMAINS, "research", "context"}
TERMINAL = {"completed", "failed", "needs_input"}
MAX_CONFIRMATIONS = 6


def route_of(decision):
    """Agent/hành động graph giao việc sau quyết định này (cùng luật với after_orchestrator)."""
    action = decision.get("action")
    if action == "delegate":
        return "delegate:" + ",".join(
            sorted(
                roster.specialist_for(t["domain"]) for t in decision.get("delegated_tasks") or []
            )
        )
    if decision.get("personalize") and action in {"research", "answer"}:
        return "context"
    if action == "tool":
        return roster.specialist_for(decision.get("domain")) or "answer"
    return action


def prompt_versions():
    """Phiên bản prompt mà mã agent đang tham chiếu (quét tĩnh), cho siêu dữ liệu lần chạy."""
    found = {}
    pattern = re.compile(r"""get_prompt\(\s*["']([\w.]+)["']\s*(?:,\s*["'](v\d+)["'])?""")
    for path in (AGENTIC / "agents").glob("*.py"):
        for name, version in pattern.findall(path.read_text()):
            found[name] = version or "v1"
    for path in (AGENTIC / "tools").glob("*.py"):
        for name, version in pattern.findall(path.read_text()):
            found[name] = version or "v1"
    return dict(sorted(found.items()))


def graph_version():
    """Dấu vân tay cấu trúc graph: tên node và cạnh của graph đã biên dịch."""
    from agentic.agents.workflow import build_workflow

    graph = build_workflow(ScriptedModels({}), EvalStore(), MemorySaver(), None, eval_settings())
    shape = graph.get_graph()
    text = (
        "\n".join(sorted(shape.nodes))
        + "\n"
        + "\n".join(sorted(f"{e.source}->{e.target}" for e in shape.edges))
    )
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def eval_settings(**overrides):
    """Mặc định production của AgentSettings, không đọc biến môi trường (tất định, chạy được trong CI)."""
    values = {
        "JEV_MODE": "off",
        "STREAM_RESPONSE_TOKENS": False,
        "AGENT_MODELS": {},
        "FALLBACK_MODEL": None,
        **overrides,
    }
    return AgentSettings.model_construct(**values)


class _Structured:
    def __init__(self, owner, role, schema):
        self.owner, self.role, self.schema = owner, role, schema

    async def ainvoke(self, messages, **kwargs):
        value = self.owner.next(self.role)
        if value is None:
            raise ValueError(f"No scripted {self.role} output")
        return self.schema.model_validate(value)


class _Tools:
    def __init__(self, owner):
        self.owner = owner

    async def ainvoke(self, messages, **kwargs):
        value = self.owner.next("tool")
        if value is None:
            return AIMessage(content=self.owner.script.get("tool_reply", "Đã xử lý."))
        calls = [
            {
                "name": c["name"],
                "args": c.get("args", {}),
                "id": c.get("id") or f"call-{uuid4().hex[:8]}",
            }
            for c in (value if isinstance(value, list) else [value])
        ]
        return AIMessage(content="", tool_calls=calls)


class ScriptedModel:
    metadata = {"hercfit_provider": "scripted", "hercfit_model": "scripted"}

    def __init__(self, owner, role):
        self.owner, self.role = owner, role

    def with_structured_output(self, schema, **kwargs):
        return _Structured(self.owner, self.role, schema)

    def bind_tools(self, tools, **kwargs):
        self.owner.bound_tools.append(sorted(t.name for t in tools))
        return _Tools(self.owner)

    async def ainvoke(self, messages, **kwargs):
        value = self.owner.next(self.role)
        return AIMessage(
            content=value if isinstance(value, str) else self.owner.script.get("reply", "Đã xử lý.")
        )


class ScriptedModels:
    """Model theo kịch bản của ca: mỗi vai trò lấy lần lượt các đầu ra đã viết sẵn; hết kịch bản thì dùng mặc định.

    `decision` hết kịch bản → quyết định trả lời (không gọi thêm tool), như router dừng lại sau khi xong việc."""

    DEFAULT_DECISION = {
        "intent": "GENERAL_CHAT",
        "next_agent": "orchestrator",
        "action": "answer",
        "instruction": "Trả lời người dùng dựa trên kết quả đã có.",
    }

    def __init__(self, script):
        self.script = script or {}
        self.cursor = {}
        self.calls = {}
        self.bound_tools = []

    def next(self, role):
        self.calls[role] = self.calls.get(role, 0) + 1
        items = self.script.get(role)
        if items is None:
            return self.DEFAULT_DECISION if role == "decision" else None
        if not isinstance(items, list):
            items = [items]
        index = self.cursor.get(role, 0)
        self.cursor[role] = index + 1
        if index < len(items):
            return items[index]
        return self.DEFAULT_DECISION if role == "decision" else None

    def get(self, role):
        return ScriptedModel(self, role)


def _initial(turn, case_id, index, user_id, previous):
    state = {
        "session_id": f"s-{case_id}",
        "user_id": user_id,
        "run_id": f"r-{case_id}-{index}",
        "messages": [HumanMessage(content=turn["message"])],
        "status": "running",
        "tool_outputs": [],
        "tool_count": 0,
        "mode": None if turn.get("mode", "normal") == "full" else turn.get("mode", "normal"),
        "user_context": None,
        "replying_to_form": bool(previous and previous.get("status") == "needs_input"),
    }
    if turn.get("food_choices") is not None:
        state["food_gap"] = (previous or {}).get("food_gap")
        state["food_choices"] = turn["food_choices"]
    return state


class GraphRuntimeAdapter:
    def __init__(self, mode="deterministic", models=None, settings=None):
        self.mode = mode
        self.models = models
        self.settings = settings

    async def run(self, case):
        from agentic.agents.workflow import build_workflow

        data = case.input
        user_id = data.get("user_id", "u-eval-1")
        backend = EvalBackend(failures=data.get("backend_failures"))
        store = EvalStore()
        scripted = ScriptedModels(data.get("script")) if self.mode == "deterministic" else None
        models = scripted or self.models
        settings = self.settings or eval_settings(**data.get("settings", {}))
        graph = build_workflow(models, store, MemorySaver(), None, settings)
        marker = request_context.set(RequestContext(user_id, token_for(user_id), backend))
        started = perf_counter()
        decisions, nodes, confirmations, errors = [], [], [], []
        result, telemetry = {}, {}
        try:
            for index, turn in enumerate(data.get("turns") or []):
                # Khi lần chạy eval được trace, span node/model của LangGraph lồng dưới trace của ca.
                config = graph_config(
                    {
                        "configurable": {"thread_id": f"{case.id}-{index}-{uuid4().hex[:6]}"},
                        "recursion_limit": settings.MAX_GRAPH_STEPS,
                    }
                )
                chat_mode = turn.get("mode", "normal")
                mode_marker = modes.current.set(modes.FULL if chat_mode == "full" else chat_mode)
                try:
                    payload = _initial(turn, case.id, index, user_id, result)
                    result = await self._drive(graph, payload, config, decisions, nodes)
                    for _ in range(MAX_CONFIRMATIONS):
                        action = result.get("pending_action")
                        if result.get("status") != "pending_confirmation" or not action:
                            break
                        decision = data.get("confirm") or "approve"
                        decision = (
                            decision[len(confirmations)] if isinstance(decision, list) else decision
                        )
                        confirmations.append(
                            {
                                "action_id": action["action_id"],
                                "tool": action["tool"],
                                "decision": decision,
                            }
                        )
                        store.rows[action["action_id"]]["status"] = (
                            "approved" if decision == "approve" else "rejected"
                        )
                        result = await self._drive(
                            graph, Command(resume={"decision": decision}), config, decisions, nodes
                        )
                finally:
                    modes.current.reset(mode_marker)
                telemetry = _merge_usage(telemetry, result.get("telemetry") or {})
        except Exception as exc:  # noqa: BLE001 - lỗi của ca được ghi vào bản ghi, không làm hỏng cả lần chạy
            errors.append(
                ErrorRecord(
                    category="provider" if classify(exc) == "provider" else "infrastructure",
                    code=type(exc).__name__,
                    message=str(exc)[:200],
                )
            )
        finally:
            request_context.reset(marker)
        return self._record(
            case,
            result,
            decisions,
            nodes,
            confirmations,
            store,
            backend,
            telemetry,
            errors,
            (perf_counter() - started) * 1000,
            scripted,
        )

    @staticmethod
    async def _drive(graph, payload, config, decisions, nodes):
        async for update in graph.astream(payload, config, stream_mode="updates"):
            for node, values in update.items():
                if node == "__interrupt__":
                    continue
                nodes.append(node)
                decision = (values or {}).get("decision") if isinstance(values, dict) else None
                if node == "orchestrator" and decision:
                    decisions.append(dict(decision))
        snapshot = await graph.aget_state(config)
        return dict(snapshot.values)

    def _record(
        self,
        case,
        state,
        decisions,
        nodes,
        confirmations,
        store,
        backend,
        telemetry,
        errors,
        elapsed,
        scripted,
    ):
        tools = []
        executed = {w["key"] for w in backend.writes}
        approved = {c["action_id"]: c["decision"] == "approve" for c in confirmations}
        for call in backend.calls:
            if call["name"] not in REGISTRY:
                continue
            tools.append(
                ToolExecutionRecord(
                    name=call["name"],
                    arguments=call["arguments"],
                    outcome="ok",
                    ok=True,
                    is_write=call["write"],
                    requires_confirmation=call["write"],
                    action_id=call["key"],
                    approved=approved.get(call["key"]) if call["write"] else None,
                    executed=call["write"] and call["key"] in executed,
                    idempotency_key=call["key"],
                    acting_user=call["user"],
                )
            )
        # Lời gọi bị chặn trước backend (không được phép, sai tham số, chờ xác nhận) chỉ thấy trong tool_outputs.
        seen_writes = {t.action_id for t in tools if t.is_write}
        for output in state.get("tool_outputs") or []:
            name = output.get("tool") or ""
            if output.get("pending") and output.get("action_id") not in seen_writes:
                tools.append(
                    ToolExecutionRecord(
                        name=name,
                        arguments=output.get("payload") or {},
                        outcome="pending_confirmation",
                        is_write=True,
                        requires_confirmation=True,
                        action_id=output.get("action_id"),
                        approved=approved.get(output.get("action_id")),
                        executed=False,
                    )
                )
            elif not output.get("ok") and not output.get("pending") and "status_code" not in output:
                tools.append(
                    ToolExecutionRecord(
                        name=name,
                        arguments=output.get("arguments") or {},
                        outcome=_blocked(output),
                        ok=False,
                        is_write=bool(getattr(REGISTRY.get(name), "write", False)),
                        error=output.get("error"),
                    )
                )
            elif "status_code" in output:
                tools.append(
                    ToolExecutionRecord(
                        name=name,
                        arguments=output.get("arguments") or {},
                        outcome="backend_error",
                        ok=False,
                        status_code=output.get("status_code"),
                        error=str(output.get("error"))[:200],
                    )
                )
        first = decisions[0] if decisions else (state.get("decision") or {})
        agents = sorted({n for n in nodes if n in AGENT_NODES})
        usage = TokenUsage(
            llm_calls=telemetry.get("llm_calls", 0),
            llm_attempts=telemetry.get("llm_attempts", 0),
            input_tokens=telemetry.get("input_tokens", 0),
            output_tokens=telemetry.get("output_tokens", 0),
            cost=telemetry.get("total_model_cost")
            if telemetry.get("model_cost_status") == "configured"
            else None,
            cost_status="configured"
            if telemetry.get("model_cost_status") == "configured"
            else "unknown",
        )
        return AgentExecutionRecord(
            case_id=case.id,
            run_id=state.get("run_id"),
            status=state.get("status") or "error",
            reply=state.get("reply") or state.get("prepared_reply"),
            route=route_of(first) if first else None,
            selected_agents=agents,
            intents=[d.get("intent") for d in decisions if d.get("intent")],
            domain=first.get("domain") if first else None,
            route_rules=[t.get("rule") for t in state.get("route_trace") or [] if t.get("rule")],
            tools=tools,
            confirmations=confirmations,
            verified_state=backend.verified_state(),
            safety=state.get("safety"),
            clarification=state.get("clarification"),
            food_gap=state.get("food_gap"),
            models={
                "mode": self.mode,
                **({"scripted_calls": str(scripted.calls)} if scripted else {}),
            },
            latency_ms=round(elapsed, 3),
            usage=usage,
            errors=errors,
        )


def _blocked(output):
    error = str(output.get("error") or "")
    if error.startswith("Tool is not allowed"):
        return "not_allowed"
    if error == "Tool call limit reached":
        return "budget_exceeded"
    if error.startswith("Deferred"):
        return "deferred"
    return "invalid_arguments"


def _merge_usage(total, telemetry):
    merged = dict(total)
    for key in ("llm_calls", "llm_attempts", "input_tokens", "output_tokens"):
        merged[key] = merged.get(key, 0) + (telemetry.get(key) or 0)
    if (
        telemetry.get("model_cost_status") == "unknown"
        or total.get("model_cost_status") == "unknown"
    ):
        merged["model_cost_status"] = "unknown"
        merged["total_model_cost"] = None
    elif telemetry.get("model_cost_status") == "configured":
        merged["model_cost_status"] = "configured"
        merged["total_model_cost"] = (total.get("total_model_cost") or 0) + (
            telemetry.get("total_model_cost") or 0
        )
    return merged


def live_models():
    """Model thật theo cấu hình agent (biến môi trường); chỉ dùng cho chế độ live."""
    from agentic.core.app.config import agent_settings
    from agentic.core.llm import Models

    return Models(agent_settings), agent_settings
