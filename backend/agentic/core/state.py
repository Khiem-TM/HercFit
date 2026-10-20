"""Shared State definitions passed between agents in the LangGraph workflow."""

from typing import Annotated, Any, Literal
from typing_extensions import TypedDict

from pydantic import BaseModel, Field

from core.llm import AnyMessage

try:
    from langgraph.graph.message import add_messages
except ImportError:

    def add_messages(left: list[Any], right: list[Any]) -> list[Any]:  # type: ignore[misc]
        return [*(left or []), *(right or [])]


IntentType = Literal["data_analysis", "backend_action", "general_chat", "finish"]
AgentNodeName = Literal["router", "data_analyst", "backend_executor", "FINISH"]


class RouteDecision(BaseModel):
    """Structured routing decision emitted by the Router/Supervisor Agent."""

    intent: IntentType = Field(
        description="Classified intent of the user's message."
    )
    next_agent: Literal["data_analyst", "backend_executor", "FINISH"] = Field(
        description="Target specialist agent node or FINISH if ready to respond directly."
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation for selecting this route.",
    )
    direct_reply: str | None = Field(
        default=None,
        description="Direct response when next_agent is FINISH and no specialist agent is required.",
    )


class AgentState(TypedDict, total=False):
    """Unified state object shared across all nodes in the Multi-Agent StateGraph."""

    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str | None
    session_id: str | None
    auth_token: str | None
    intent: IntentType | None
    next_agent: str | None
    reasoning: str | None
    context: dict[str, Any]
    tool_outputs: list[dict[str, Any]]
    iteration_count: int
    error: str | None

