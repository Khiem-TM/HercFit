from typing import Annotated, Any, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, ConfigDict, Field
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Domain = Literal['profile', 'metrics', 'goals', 'meals', 'trainings', 'foods', 'exercises', 'progress']

class RouteDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intent: str
    next_agent: Literal['tool', 'research', 'orchestrator']
    domain: Domain | None = None
    action: Literal['answer', 'clarify', 'tool', 'research', 'finish']
    instruction: str = Field(description='Concrete next task, not private reasoning')
    missing_fields: list[str] = Field(default_factory=list)
    research_query: str | None = Field(default=None, description='Only public food/exercise name, no personal details')
    explicit_web_request: bool = False

class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    session_id: str
    session_generation: int
    run_id: str
    decision: dict[str, Any]
    tool_outputs: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    approved: bool
    status: str
    reply: str
    tool_count: int
    research_count: int
    sources: list[dict[str, Any]]
    candidate: dict[str, Any] | None
    error: str | None
    graph_context: dict[str, Any] | None
    graph_retrieval_attempted: bool
    graph_context_run_id: str | None
    fast_read_plan: dict[str, Any] | None
    fast_read_complete: bool
    telemetry: dict[str, Any]
    execution_records: list[dict[str, Any]]
