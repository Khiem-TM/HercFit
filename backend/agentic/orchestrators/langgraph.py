from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from agentic.agents import roster
from agentic.agents.orchestration_agent import OrchestrationAgent
from agentic.agents.research_agent import ResearchV2
from agentic.agents.specialists import SPECIALISTS
from agentic.agents.tool_agent import ToolAgent
from agentic.core.context import request_context
from agentic.knowledge_graph.context import pipeline as context_pipeline
from agentic.knowledge_graph.context.graph import ContextGraph
from agentic.observability import annotate, span
from agentic.observability.execution import run_node
from agentic.observability.telemetry import MeasuredModels
from agentic.services import personal_context
from agentic.services.write_reply import executed_writes
from agentic.workflows import delegation, mode
from agentic.workflows.adaptive_router import verify_read_event
from agentic.workflows.context import decision_domains, retrieve_graph_context
from agentic.workflows.routing import (
    fast_reads_enabled,
    latest_request,
    make_fast_read_plan,
)
from agentic.workflows.specialist_graph import build_specialist_graph
from agentic.workflows.state import AgentState


def build_workflow(models, store, saver, tavily, settings, graph_context=None, jev=None):
    models = MeasuredModels(models)
    orchestrator = OrchestrationAgent(models, settings, jev=jev)
    tool = ToolAgent(models, store, settings)
    specialists = {agent.name: agent(models, store, settings) for agent in SPECIALISTS}
    research = ResearchV2(models, tavily, store, settings, jev=jev)
    graph = StateGraph(AgentState)

    async def guarded(fn, state, node, agent=None):
        # Agent của node chọn model riêng (AGENT_MODELS) và gắn nhãn số đo cho mọi lời gọi model trong node.
        with roster.acting(agent):
            return await run_node(fn, state, node, settings)

    async def decide_step(state):
        update = {}
        current = dict(state)
        policy = mode.policy(state)
        if (
            policy.personal_card
            and "card" in personal_context.sources(settings)
            and current.get("user_context_run_id") != current.get("run_id")
        ):
            ctx = request_context.get(None)
            card = await personal_context.load_card(ctx.backend, ctx.token) if ctx else None
            update = {**update, "user_context": card, "user_context_run_id": current.get("run_id")}
            current.update(update)
        result = await orchestrator.decide(current)
        if "fast_read_plan" in result:
            return {**update, **result}
        current.update(result)
        decision = result.get("decision") or {}
        # Nạp ngữ cảnh chung cho các nhánh song song trước khi giao việc.
        named = [
            d
            for task in [decision, *(decision.get("delegated_tasks") or [])]
            for d in decision_domains(task)
        ]
        missed = list(dict.fromkeys(named))
        if missed:
            update = {
                **update,
                **await retrieve_graph_context(
                    current, missed, settings=settings, graph_context=graph_context
                ),
            }
            current.update(update)
        if (state.get("turn") or {}).get("run_id") != state.get("run_id") and decision:
            # Quyết định định tuyến đầu tiên đặt tên cho lượt; các quyết định sau chỉ tiếp nối nó.
            result["turn"] = {
                "run_id": state.get("run_id"),
                "intent": decision.get("intent"),
                "domain": decision.get("domain"),
                "action": decision.get("action"),
                # Nhu cầu truy hồi router nêu (focus, entities, khoảng ngày): các bước sau có thể thay decision, còn
                # đây là intent truy hồi gốc của lượt, để đo đúng chất lượng định tuyến cho context graph.
                "context": decision.get("context"),
                "plan_task": decision.get("plan_task"),
            }
        plan = None
        if fast_reads_enabled(settings):
            plan = make_fast_read_plan(current)
        return {
            **update,
            **result,
            "fast_read_plan": plan.model_dump(mode="json") if plan else None,
            "fast_read_complete": False,
        }

    async def decide(state):
        result = await guarded(decide_step, state, "orchestrator", roster.SUPERVISOR)
        if result.get("status") == "failed" and "decision" not in result:
            result["decision"] = {
                "action": "answer",
                "instruction": "Thông báo không thể phân loại yêu cầu.",
            }
        return result

    async def answer(state):
        if verify_read_event(state):
            route = (
                "jev_read" if (state.get("fast_read_plan") or {}).get("source") == "jev"
                else "llm_fallback"
            )
            with span("jev.answer", route=route) as observation:
                result = await answer_step(state)
                annotate(jev_answer_status=result.get("status"))
                if observation:
                    observation.add_metadata({"status": result.get("status")})
                return result
        return await answer_step(state)

    async def answer_step(state):
        if state.get("model_auth_failed"):
            # Model trả lời dùng chung thông tin xác thực này. Một request khác không thể
            # khắc phục lỗi 401 và sẽ che lỗi gốc bằng lỗi thứ hai.
            from langchain_core.messages import AIMessage

            reply = state["error"]
            return {
                "reply": reply,
                "status": "failed",
                "messages": [AIMessage(content=reply, name="orchestration_agent")],
            }
        result = await guarded(orchestrator.answer, state, "answer", roster.SYNTHESIZER)
        if "reply" not in result:
            from langchain_core.messages import AIMessage

            result["reply"] = (
                state.get("error") or "Dịch vụ trả lời hiện không khả dụng. Vui lòng thử lại."
            )
            result["messages"] = [AIMessage(content=result["reply"], name="orchestration_agent")]
        return result

    async def await_confirmation(state):
        decision = interrupt(state["pending_action"])
        if decision.get("decision") == "approve":
            # Bản người dùng sửa trên thẻ đã được runtime kiểm tra và lưu vào hành động đang chờ.
            edited = decision.get("action")
            # Bộ nhớ quyết định: chỉ tên các trường người dùng đã sửa, không bao giờ giá trị.
            original = state["pending_action"].get("payload") or {}
            changed = sorted(
                k for k, v in ((edited or {}).get("payload") or {}).items() if original.get(k) != v
            )
            return {
                "approved": True,
                "action_decision": "approved",
                "edited_fields": [*(state.get("edited_fields") or []), *changed][:10],
                **({"pending_action": {**state["pending_action"], **edited}} if edited else {}),
            }
        rejected = delegation.after_reject(state)
        if rejected:
            return {**rejected, "action_decision": "rejected"}
        from langchain_core.messages import AIMessage

        reply = "Đã từ chối thao tác; không ghi dữ liệu."
        if (state.get("decision") or {}).get("replace_training_plan"):
            if any(output["tool"] == "end_training_plan" for output in executed_writes(state)):
                reply = "Lịch cũ đã dừng. Bạn đã từ chối lịch mới nên lịch mới chưa được lưu."
            elif state["pending_action"]["tool"] == "end_training_plan":
                reply = "Bạn đã từ chối dừng lịch hiện tại. Lượt này chưa thay đổi lịch tập."
        return {
            "approved": False,
            "action_decision": "rejected",
            "pending_action": None,
            "status": "completed",
            "reply": reply,
            "messages": [AIMessage(content=reply, name="orchestration_agent")],
        }

    graph.add_node("orchestrator", decide)

    async def context_step(state):
        decision = state["decision"]
        topic = decision.get("topic") or "general"
        reads = personal_context.deep_reads(topic)
        inventory = (state.get("user_context") or {}).get("inventory") or {}
        if not inventory.get("health_shared_with_assistant"):
            # Dữ liệu thiết bị chỉ khi người dùng đồng ý (backend cũng kiểm tra điều này).
            reads = [
                (name, args) for name, args in reads if not name.startswith(("get_health", "list_"))
            ]
        if "backend_reads" not in personal_context.sources(settings):
            reads = []
        result = await tool.read_context(state, reads) if reads else {}
        outputs = {o["tool"]: o for o in result.get("tool_outputs", [])}
        trace = {
            "stage": "context",
            "topic": topic,
            "reads": [
                {"tool": name, "ok": bool((outputs.get(name) or {}).get("ok"))} for name, _ in reads
            ],
        }
        annotate(personal_topic=topic, personal_reads=len(reads))
        return {
            **result,
            "personal_reads_done": True,
            "route_trace": [*(state.get("route_trace") or []), trace],
        }

    async def invoke_context(state):
        return await guarded(context_step, state, "context")

    def needs_context_graph(s):
        decision = s.get("decision") or {}
        return bool(
            graph_context is not None
            and "context_graph" in personal_context.sources(settings)
            and decision.get("context")
            and s.get("context_graph_run_id") != s.get("run_id")
            and decision.get("action") in {"answer", "tool", "research"}
            and not decision.get("delegated_tasks")
        )

    async def context_graph_step(state):
        """Truy vấn context graph cho lượt này, với đường đọc backend dự phòng."""
        decision = state["decision"]
        ctx = request_context.get(None)
        if ctx is None or ctx.user_id != state.get("user_id"):
            built = ContextGraph(status="blocked")
        else:
            built = await context_pipeline.build(
                graph_context,
                models,
                owner=ctx.user_id,
                session_id=state.get("session_id"),
                question=latest_request(state),
                decision=decision,
            )
        update = {
            "context_graph": built.model_dump(mode="json"),
            "context_graph_run_id": state.get("run_id"),
        }
        trace = {
            "stage": "context_graph",
            "status": built.status,
            "source": built.source,
            "rows": len(built.rows),
        }
        if (
            not built.usable
            and decision.get("action") == "answer"
            and not decision.get("personalize")
            and roster.specialist_for(decision.get("domain"))
        ):
            update["decision"] = {
                **decision,
                "action": "tool",
                "next_agent": "tool",
                "read_only": True,
                "instruction": "Đọc dữ liệu đã lưu từ backend để trả lời: "
                + decision.get("instruction", ""),
            }
            trace["fallback"] = "backend_read"
        annotate(context_fallback=trace.get("fallback"))
        update["route_trace"] = [*(state.get("route_trace") or []), trace]
        return update

    async def invoke_context_graph(state):
        result = await guarded(context_graph_step, state, "context_graph", roster.CONTEXT)
        # Kể cả khi bước lỗi: đánh dấu đã thử, nếu không after_orchestrator sẽ quay lại nút này mãi.
        result.setdefault("context_graph_run_id", state.get("run_id"))
        return result

    async def invoke_research(state):
        return await guarded(research.invoke, state, "research", roster.RESEARCH)

    async def execute(state):
        return delegation.next_card(state, await guarded(tool.execute, state, "execute"))

    subgraphs = {
        name: build_specialist_graph(agent, settings, graph_context, guarded)
        for name, agent in specialists.items()
    }

    async def delegate(state, config):
        """Một nhánh song song (Send): agent sở hữu miền của nhiệm vụ làm việc trên state riêng của nhánh."""
        name = roster.specialist_for(state["decision"]["domain"])
        result = await subgraphs[name].ainvoke(state, config)
        return {"agent_results": [delegation.outcome(name, state, result)]}

    async def join(state):
        return delegation.join(state)

    for name, subgraph in subgraphs.items():
        graph.add_node(name, subgraph)
    graph.add_node("delegate", delegate)
    graph.add_node("join", join)
    graph.add_node("research", invoke_research)
    graph.add_node("context", invoke_context)
    graph.add_node("context_graph", invoke_context_graph)
    graph.add_node("confirmation", await_confirmation)
    graph.add_node("execute", execute)
    graph.add_node("answer", answer)
    graph.add_edge(START, "orchestrator")

    def after_orchestrator(s):
        decision = s["decision"]
        if needs_context_graph(s):
            return "context_graph"
        if (
            decision.get("personalize")
            and not s.get("personal_reads_done")
            and decision["action"] in {"research", "answer"}
        ):
            return "context"
        if decision["action"] == "delegate" and decision.get("delegated_tasks"):
            return [
                Send("delegate", delegation.branch(s, task)) for task in decision["delegated_tasks"]
            ]
        if decision["action"] == "tool":
            return roster.specialist_for(decision.get("domain")) or "answer"
        return "research" if decision["action"] == "research" else "answer"

    graph.add_conditional_edges(
        "orchestrator",
        after_orchestrator,
        [*specialists, "delegate", "research", "answer", "context", "context_graph"],
    )
    graph.add_conditional_edges(
        "context_graph",
        after_orchestrator,
        [*specialists, "delegate", "research", "answer", "context"],
    )
    graph.add_edge("delegate", "join")
    graph.add_conditional_edges(
        "join",
        lambda s: (
            "confirmation"
            if s.get("pending_action")
            else ("answer" if delegation.answers(s) else "orchestrator")
        ),
        ["confirmation", "answer", "orchestrator"],
    )
    graph.add_conditional_edges(
        "context",
        lambda s: "research" if s["decision"]["action"] == "research" else "answer",
        {"research": "research", "answer": "answer"},
    )

    def after_specialist(s):
        if s.get("pending_action"):
            return "confirmation"
        if (
            (s.get("fast_read_plan") or {}).get("source") == "jev"
            and (s.get("decision") or {}).get("action") == "answer"
        ):
            return "answer"
        if s.get("status") == "running" and (
            s.get("prepared_reply")
            or (s.get("fast_read_complete") and s.get("decision", {}).get("action") == "answer")
        ):
            return "answer"
        return "orchestrator"

    for name in specialists:
        graph.add_conditional_edges(
            name, after_specialist, ["confirmation", "answer", "orchestrator"]
        )

    def after_research(s):
        decision = s.get("decision") or {}
        if decision.get("plan_task") == "plan_build" and s.get("status") == "running":
            return "orchestrator"  # chế độ Plan: nguyên tắc đã tra cứu, tiếp theo dựng lịch tập bằng tool
        if (
            decision.get("personalize")
            or s.get("research_answer")
            or s.get("prepared_reply")
            or s.get("status") in {"needs_input", "failed"}
        ):
            return "answer"
        return "orchestrator"

    graph.add_conditional_edges("research", after_research)

    def after_confirmation(s):
        if s.get("approved"):
            return "execute"
        if s.get("pending_action"):
            return "confirmation"  # thẻ kế tiếp của lượt giao việc song song
        if s.get("status") == "running":
            return "answer" if delegation.answers(s) else "orchestrator"
        return END

    graph.add_conditional_edges(
        "confirmation",
        after_confirmation,
        ["execute", "confirmation", "answer", "orchestrator", END],
    )
    # Lệnh finalize bị từ chối với 409 quay lại dưới dạng bản xem trước mới cần được xác nhận riêng.
    graph.add_conditional_edges(
        "execute",
        lambda s: (
            "confirmation"
            if s.get("status") == "pending_confirmation"
            else ("answer" if delegation.answers(s) else "orchestrator")
        ),
    )
    graph.add_edge("answer", END)
    return graph.compile(checkpointer=saver)
