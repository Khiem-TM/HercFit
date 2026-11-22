from langgraph.graph import END, START, StateGraph

from agentic.observability import annotate, span
from agentic.tools.policy import continue_catalog_lookup
from agentic.workflows.context import retrieve_graph_context
from agentic.workflows.routing import (
    FastReadPlan,
    fast_answer_instruction,
    fast_reads_enabled,
    make_fast_read_plan,
)
from agentic.workflows.state import AgentState


def build_specialist_graph(agent, settings, graph_context, guarded):
    """Dựng subgraph chạy một agent chuyên trách và vòng tra catalog của nó."""

    async def jev_read(state, fast_plan):
        decision = state["decision"]
        with span("jev.read", "tool", domain=decision.get("domain")) as observation:
            enabled = (
                settings.JEV_MODE != "off"
                and settings.JEV_ROUTING_PROFILE == "verify_read"
                and "routing" in settings.JEV_ENABLED_PHASES
                and fast_reads_enabled(settings)
            )
            result = await agent.invoke_fast(state) if enabled else None
            if result is None:
                annotate(
                    jev_read_outcome="fallback",
                    jev_read_reason="invalid_plan" if enabled else "disabled",
                )
                # Giữ turn hiện tại để router xử lý lại mà không gọi Jev lần nữa.
                return {"fast_read_plan": None, "decision": {}}

            plan = FastReadPlan.model_validate(fast_plan)
            output = result["tool_outputs"][-1]
            annotate(jev_template_id=plan.template_id, tool=plan.tool)
            if result["fast_read_complete"]:
                annotate(jev_read_outcome="empty" if output.get("not_found") else "ok")
            else:
                annotate(jev_read_outcome="failed", http_status=output.get("status_code"))
                if observation:
                    observation.add_metadata({"status": "failed"})
                result["status"] = "failed"
            result["decision"] = {
                **decision,
                "action": "answer",
                "next_agent": "orchestrator",
                "instruction": fast_answer_instruction(plan),
            }
            trace = {"stage": "agent", "agent": agent.name, "domain": decision.get("domain")}
            result["route_trace"] = [*(state.get("route_trace") or []), trace]
            return result

    async def specialist_step(state):
        decision = state.get("decision", {})
        domain = decision.get("domain")
        fast_plan = state.get("fast_read_plan") or {}
        if fast_plan.get("source") == "jev":
            return await jev_read(state, fast_plan)
        # Lệnh ghi dựng sẵn (simple_writes) chạy không qua model, nên không ai đọc thẻ KG: bỏ lần đọc graph.
        update = (
            {}
            if decision.get("code_call")
            else await retrieve_graph_context(
                state, [domain], settings=settings, graph_context=graph_context
            )
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

    async def act(state):
        return await guarded(specialist_step, state, agent.name, agent.name)

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
