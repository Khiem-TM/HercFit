from typing import Annotated, Any, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema # Loại bỏ trường khỏi JSON schema
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Domain = Literal['profile', 'metrics', 'goals', 'meals', 'trainings', 'foods', 'exercises', 'progress', 'training_plans', 'coaching']

# Điều phối response model trả về --> Hỗ trợ orschestration
class RouteDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intent: str
    next_agent: Literal['tool', 'research', 'orchestrator']
    domain: Domain | None = None
    action: Literal['answer', 'clarify', 'tool', 'research', 'finish']
    instruction: str = Field(description='Concrete next task, not private reasoning')
    missing_fields: list[str] = Field(default_factory=list)
    research_query: str | None = Field(default=None, description='Public food/exercise name or sports knowledge question; no personal details', max_length=180)
    explicit_web_request: bool = False
    objectives: list[str] = Field(default_factory=list, max_length=3)
    research_queries: list[str] = Field(default_factory=list, max_length=3)
    create_distinct: SkipJsonSchema[bool] = False
    read_only: SkipJsonSchema[bool] = False

class AgentState(TypedDict, total=False):
    model_auth_failed: bool
    jev_events: list[dict[str, Any]]
    jev_rejections: dict[str, Any]
    catalog_handoff: dict[str, Any] | None
    catalog_recovery_domains: list[str]
    research_usage: dict[str, Any]
    research_work: dict[str, Any]
    research_result: dict[str, Any]
    research_answer: str | None
    research_trace: list[dict[str, Any]]
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    session_id: str
    session_generation: int
    run_id: str
    trace_context: dict[str, Any] | None
    decision: dict[str, Any]
    tool_outputs: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    clarification: dict[str, Any] | None
    research_handoff: dict[str, Any] | None
    catalog_choice: dict[str, Any] | None
    catalog_draft: dict[str, Any] | None
    prepared_reply: str | None
    illustrations: list[dict[str, Any]]
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
    graph_context_domains: list[str]
    graph_context_run_id: str | None
    turn: dict[str, Any] | None
    fast_read_plan: dict[str, Any] | None
    fast_read_complete: bool
    telemetry: dict[str, Any]
    execution_records: list[dict[str, Any]]
    session_memory: dict[str, Any] | None
    safety: dict[str, Any] | None
