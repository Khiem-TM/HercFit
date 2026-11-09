from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from agentic.agents.orchestration_agent import OrchestrationAgent
from agentic.agents.research_agent import ResearchV2
from agentic.agents.specialists import SPECIALISTS
from agentic.agents.state import AgentState
from agentic.agents.tool_agent import ToolAgent
from agentic.core import roster
from agentic.core.context import request_context
from agentic.knowledge_graph.service import domains_for
from agentic.observability import annotate
from agentic.observability.execution import run_node
from agentic.observability.telemetry import MeasuredModels
from agentic.security.content_filter import assess
from agentic.services import delegation, food_suggestion, mode, personal_context
from agentic.services.rag_pipeline import decision_domains, retrieve_graph_context
from agentic.services.routing import (
    fast_reads_enabled,
    fast_route,
    latest_request,
    make_fast_read_plan,
)
from agentic.tools.policy import continue_catalog_lookup


def build_workflow(models, store, saver, tavily, settings, graph_context=None, jev=None):
    models = MeasuredModels(models)
    orchestrator = OrchestrationAgent(models, settings, jev=jev)
    # Bộ thực thi dùng chung, không thuộc agent nào: cổng ghi HITL (execute) và các lần đọc ngữ cảnh cá nhân do code chọn.
    tool = ToolAgent(models, store, settings)
    specialists = {agent.name: agent(models, store, settings) for agent in SPECIALISTS}
    research = ResearchV2(models, tavily, store, settings, jev=jev)
    graph = StateGraph(AgentState)

    async def guarded(fn, state, node, agent=None):
        # Agent của node chọn model riêng (AGENT_MODELS) và gắn nhãn số đo cho mọi lời gọi model trong node.
        with roster.acting(agent):
            return await run_node(fn, state, node, settings)

    async def decide_step(state):
        hinted = domains_for(latest_request(state))
        update = await retrieve_graph_context(
            state, hinted, settings=settings, graph_context=graph_context
        )
        current = {**state, **update}
        policy = mode.policy(state)
        # Chế độ Plan không có lối tắt đọc theo mẫu: người dùng đã chọn tư vấn chuyên sâu.
        # Lựa chọn trên thẻ món thiếu đi thẳng tới bước dựng bữa của orchestrator, không qua lối tắt đọc theo mẫu.
        shortcuts = (
            policy.shortcuts
            and assess(latest_request(current)) is None
            and not current.get("food_choices")
        )
        routed = fast_route(current) if fast_reads_enabled(settings) and shortcuts else None
        if routed and not policy.allows(routed[0]["domain"]):
            # Mẫu đọc nhanh của miền ngoài chế độ (vd. dữ liệu sức khoẻ ở chế độ thường) đi qua router để được mời sang Plan.
            routed = None
        if routed:
            # Lệnh đọc độc lập khớp một mẫu chặt chẽ: không gọi model định tuyến hay chọn tool.
            decision, plan = routed
            annotate(fast_route=plan.template_id)
            return {
                **update,
                "decision": decision,
                "status": "running",
                "fast_read_plan": plan.model_dump(mode="json"),
                "fast_read_complete": False,
                "turn": {
                    "run_id": state.get("run_id"),
                    "intent": decision["intent"],
                    "domain": decision["domain"],
                    "action": decision["action"],
                },
            }
        if (
            shortcuts
            and food_suggestion.is_food_suggestion(latest_request(current))
            and not current.get("tool_outputs")
            and not current.get("pending_action")
            and (state.get("turn") or {}).get("run_id") != state.get("run_id")
        ):
            # Gợi ý bữa ăn độc lập: một lần tra catalog chỉ đọc, không gọi model định tuyến.
            decision = food_suggestion.lookup_decision()
            annotate(route="food_suggestion")
            return {
                **update,
                "decision": decision,
                "status": "running",
                "fast_read_plan": None,
                "fast_read_complete": False,
                "turn": {
                    "run_id": state.get("run_id"),
                    "intent": decision["intent"],
                    "domain": decision["domain"],
                    "action": decision["action"],
                },
            }
        if policy.personal_card and current.get("user_context_run_id") != current.get("run_id"):
            # Một lần mỗi lượt chạy: những gì HercFit đã biết về người dùng, để router đọc thay vì hỏi.
            ctx = request_context.get(None)
            card = await personal_context.load_card(ctx.backend, ctx.token) if ctx else None
            update = {**update, "user_context": card, "user_context_run_id": current.get("run_id")}
            current.update(update)
        result = await orchestrator.decide(current)
        current.update(result)
        decision = result.get("decision") or {}
        # Cách diễn đạt có thể không gọi tên miền graph nào ("pace 5K của tôi"): đọc ngay miền của router và
        # chủ đề cá nhân, để câu trả lời, ngữ cảnh và tra cứu thấy được thẻ, không chỉ các lời gọi tool.
        # Các miền bước này đã thử được để lại cho các bước sau (timeout không được thử lại ở đây).
        # Lượt giao việc song song: đọc trước miền của mọi nhiệm vụ, để các nhánh dùng chung một ngữ cảnh graph.
        named = [
            d
            for task in [decision, *(decision.get("delegated_tasks") or [])]
            for d in decision_domains(task)
        ]
        missed = [d for d in dict.fromkeys(named) if d not in hinted]
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
            return {
                "approved": True,
                **({"pending_action": {**state["pending_action"], **edited}} if edited else {}),
            }
        rejected = delegation.after_reject(state)
        if rejected:
            return rejected  # lượt giao việc song song: thẻ kế tiếp, hoặc trả lời các phần còn lại
        from langchain_core.messages import AIMessage

        reply = "Đã từ chối thao tác; không ghi dữ liệu."
        return {
            "approved": False,
            "pending_action": None,
            "status": "completed",
            "reply": reply,
            "messages": [AIMessage(content=reply, name="orchestration_agent")],
        }

    graph.add_node("orchestrator", decide)

    async def specialist_step(agent, state):
        domain = state.get("decision", {}).get("domain")
        update = await retrieve_graph_context(
            state, [domain], settings=settings, graph_context=graph_context
        )
        # Vết định tuyến ghi agent nhận việc, một lần mỗi lần được giao (vòng tra catalog bên trong không ghi lại).
        trace = state.get("route_trace") or []
        entry = {"stage": "agent", "agent": agent.name, "domain": domain}
        if trace[-1:] != [entry]:
            update["route_trace"] = [*trace, entry]
        current = {**state, **update}
        if fast_reads_enabled(settings) and not current.get("fast_read_plan"):
            plan = make_fast_read_plan(current)
            if plan:
                update["fast_read_plan"] = plan.model_dump(mode="json")
                current.update(update)
        result = await agent.act(current)
        return {**update, **result}

    def specialist(agent):
        """Subgraph của một agent chuyên trách: làm việc, và tiếp tục ngay khi vừa tra catalog mà miền nhật ký phụ thuộc
        (ví dụ tra món rồi ghi bữa ăn). Bản xem trước, câu trả lời và lần định tuyến tiếp theo thuộc graph chính."""

        async def act(state):
            return await guarded(
                lambda current: specialist_step(agent, current), state, agent.name, agent.name
            )

        subgraph = StateGraph(AgentState)
        subgraph.add_node("act", act)
        subgraph.add_edge(START, "act")
        subgraph.add_conditional_edges(
            "act",
            lambda s: "act" if not s.get("pending_action") and continue_catalog_lookup(s) else END,
            ["act", END],
        )
        # Không checkpoint riêng: subgraph không có interrupt và runtime chỉ chạy tiếp tại confirmation/execute, nên
        # checkpoint của graph chính sau node là đủ; không lưu thêm bản sao state (kèm tin nhắn) vào database.
        return subgraph.compile(checkpointer=False)

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

    async def invoke_research(state):
        return await guarded(research.invoke, state, "research", roster.RESEARCH)

    async def execute(state):
        # Lượt giao việc song song: sau mỗi lệnh ghi, bản xem trước kế tiếp trong hàng đợi lên thẻ.
        return delegation.next_card(state, await guarded(tool.execute, state, "execute"))

    subgraphs = {name: specialist(agent) for name, agent in specialists.items()}

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
    graph.add_node("confirmation", await_confirmation)
    graph.add_node("execute", execute)
    graph.add_node("answer", answer)
    graph.add_edge(START, "orchestrator")

    def after_orchestrator(s):
        decision = s["decision"]
        if (
            decision.get("personalize")
            and not s.get("personal_reads_done")
            and decision["action"] in {"research", "answer"}
        ):
            return "context"  # dữ liệu của người dùng trước bước tra cứu hoặc trả lời
        if decision["action"] == "delegate" and decision.get("delegated_tasks"):
            # Tin nhắn nhiều ý: mỗi nhiệm vụ một nhánh song song trên state riêng; join gộp kết quả.
            return [
                Send("delegate", delegation.branch(s, task)) for task in decision["delegated_tasks"]
            ]
        if decision["action"] == "tool":
            # Supervisor giao việc cho agent chuyên trách sở hữu miền của quyết định.
            return roster.specialist_for(decision.get("domain")) or "answer"
        return "research" if decision["action"] == "research" else "answer"

    graph.add_conditional_edges(
        "orchestrator",
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

    # Câu trả lời do code viết (những gì lệnh ghi đã xác nhận đã lưu) kết thúc lượt mà không gọi định tuyến thêm.
    def after_specialist(s):
        if s.get("pending_action"):
            return "confirmation"
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

    # Câu trả lời cá nhân hoá được viết từ dữ liệu của người dùng và bằng chứng tra cứu, dù tra cứu tìm được gì.
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
