"""Multi-Agent StateGraph workflow orchestration connecting Router, DataAnalyst, and BackendExecutor."""

from collections.abc import AsyncGenerator
from typing import Any, Callable, Literal

from agents.backend_executor_agent import BackendExecutorAgent
from agents.data_analyst_agent import DataAnalystAgent
from agents.router_agent import RouterAgent
from clients.backend_client import BackendClient
from core.state import AgentState
from graph.checkpoints import BaseCheckpointSaver, CheckpointManager

try:
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.state import CompiledStateGraph
except ImportError:
    START = "__start__"
    END = "__end__"

    class CompiledStateGraph:  # type: ignore[no-redef]
        """Lightweight async StateGraph runner when langgraph is not installed on host."""

        def __init__(
            self,
            nodes: dict[str, Callable[..., Any]],
            edges: dict[str, str],
            conditional_edges: dict[str, tuple[Callable[[AgentState], str], dict[str, str]]],
            checkpointer: Any = None,
        ) -> None:
            self.nodes = nodes
            self.edges = edges
            self.conditional_edges = conditional_edges
            self.checkpointer = checkpointer

        @staticmethod
        def _merge_state(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
            merged = dict(current)
            for k, v in (updates or {}).items():
                if k == "messages":
                    merged["messages"] = [*(merged.get("messages") or []), *(v or [])]
                else:
                    merged[k] = v
            return merged

        async def ainvoke(
            self, input_state: dict[str, Any], config: Any = None, **kwargs: Any
        ) -> dict[str, Any]:
            state = dict(input_state)
            curr = self.edges.get(START)
            steps = 0
            while curr and curr != END and steps < 10:
                steps += 1
                node_fn = self.nodes[curr]
                updates = await node_fn(state, config=config)
                state = self._merge_state(state, updates)
                if curr in self.conditional_edges:
                    cond_fn, mapping = self.conditional_edges[curr]
                    branch_key = cond_fn(state)
                    curr = mapping.get(branch_key, END)
                else:
                    curr = self.edges.get(curr, END)
            return state

        async def astream(
            self, input_state: dict[str, Any], config: Any = None, **kwargs: Any
        ) -> AsyncGenerator[dict[str, Any], None]:
            state = dict(input_state)
            curr = self.edges.get(START)
            steps = 0
            while curr and curr != END and steps < 10:
                steps += 1
                node_fn = self.nodes[curr]
                updates = await node_fn(state, config=config)
                state = self._merge_state(state, updates)
                yield {curr: updates}
                if curr in self.conditional_edges:
                    cond_fn, mapping = self.conditional_edges[curr]
                    branch_key = cond_fn(state)
                    curr = mapping.get(branch_key, END)
                else:
                    curr = self.edges.get(curr, END)

    class StateGraph:  # type: ignore[no-redef]
        def __init__(self, state_schema: Any) -> None:
            self.state_schema = state_schema
            self._nodes: dict[str, Callable[..., Any]] = {}
            self._edges: dict[str, str] = {}
            self._conditional_edges: dict[
                str, tuple[Callable[[AgentState], str], dict[str, str]]
            ] = {}

        def add_node(self, name: str, action: Callable[..., Any]) -> None:
            self._nodes[name] = action

        def add_edge(self, start_key: str, end_key: str) -> None:
            self._edges[start_key] = end_key

        def add_conditional_edges(
            self,
            source: str,
            path: Callable[[AgentState], str],
            path_map: dict[str, str],
        ) -> None:
            self._conditional_edges[source] = (path, path_map)

        def compile(self, checkpointer: Any = None) -> CompiledStateGraph:
            return CompiledStateGraph(
                nodes=self._nodes,
                edges=self._edges,
                conditional_edges=self._conditional_edges,
                checkpointer=checkpointer,
            )


def _route_from_supervisor(
    state: AgentState,
) -> Literal["data_analyst", "backend_executor", "__end__"]:
    next_agent = state.get("next_agent")
    if next_agent == "data_analyst":
        return "data_analyst"
    if next_agent == "backend_executor":
        return "backend_executor"
    return "__end__"


def build_agent_graph(
    *,
    router_agent: RouterAgent | None = None,
    data_analyst_agent: DataAnalystAgent | None = None,
    backend_executor_agent: BackendExecutorAgent | None = None,
    backend_client: BackendClient | None = None,
) -> StateGraph:
    """Construct the uncompiled Multi-Agent StateGraph with nodes and conditional edges."""
    supervisor = router_agent or RouterAgent()
    analyst = data_analyst_agent or DataAnalystAgent()
    executor = backend_executor_agent or BackendExecutorAgent(
        backend_client=backend_client
    )

    workflow = StateGraph(AgentState)

    workflow.add_node("router", supervisor.ainvoke)
    workflow.add_node("data_analyst", analyst.ainvoke)
    workflow.add_node("backend_executor", executor.ainvoke)

    workflow.add_edge(START, "router")
    workflow.add_conditional_edges(
        "router",
        _route_from_supervisor,
        {
            "data_analyst": "data_analyst",
            "backend_executor": "backend_executor",
            "__end__": END,
        },
    )
    workflow.add_edge("data_analyst", "router")
    workflow.add_edge("backend_executor", "router")

    return workflow


def compile_agent_workflow(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    backend_client: BackendClient | None = None,
) -> CompiledStateGraph:
    """Compile the Multi-Agent StateGraph with an optional checkpointer."""
    saver = checkpointer or CheckpointManager().get_default_saver()
    graph = build_agent_graph(backend_client=backend_client)
    return graph.compile(checkpointer=saver)

