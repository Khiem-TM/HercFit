from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema  # Loại bỏ trường khỏi JSON schema
from typing_extensions import TypedDict

Domain = Literal[
    "profile",
    "metrics",
    "goals",
    "meals",
    "trainings",
    "foods",
    "exercises",
    "progress",
    "training_plans",
    "coaching",
    "health",
]


class MealLogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    food: str = Field(
        max_length=80, description="Food name exactly as the user said it, without quantity words"
    )
    quantity: float | None = Field(
        default=None,
        gt=0,
        le=5000,
        description="Amount the user stated; null when they did not say how much",
    )
    unit: Literal["SERVING", "G", "ML"] | None = Field(
        default=None,
        description="SERVING for counted portions (cái, bát, tô, đĩa, suất, ly, cốc, phần, quả); "
        "G or ML only when the user gave grams/millilitres; null when unknown",
    )


class MealLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(
        default=None, max_length=120, description="Short meal name, e.g. Bữa sáng, Bữa trưa"
    )
    consumed_at: str | None = Field(
        default=None,
        description="ISO 8601 time with offset, resolved from the current time "
        "(sáng nay, trưa nay, vừa xong); null when unknown",
    )
    items: list[MealLogItem] = Field(default_factory=list, max_length=5)


# Điều phối response model trả về --> Hỗ trợ orschestration
class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str
    next_agent: Literal["tool", "research", "orchestrator"]
    domain: Domain | None = None
    action: Literal["answer", "clarify", "tool", "research", "finish"]
    instruction: str = Field(description="Concrete next task, not private reasoning")
    missing_fields: list[str] = Field(default_factory=list)
    research_query: str | None = Field(
        default=None,
        description="Public food/exercise name or sports knowledge question; no personal details",
        max_length=180,
    )
    explicit_web_request: bool = False
    objectives: list[str] = Field(default_factory=list, max_length=3)
    research_queries: list[str] = Field(default_factory=list, max_length=3)
    personalize: bool = Field(
        default=False,
        description="Advice or analysis about this user's own body/training/nutrition: read their stored data first",
    )
    topic: (
        Literal[
            "running",
            "strength",
            "training",
            "nutrition",
            "body",
            "recovery",
            "wellbeing",
            "general",
        ]
        | None
    ) = Field(
        default=None,
        description="Subject of a personalized request; selects which stored analytics are read",
    )
    plan_task: Literal["advice", "life_review", "plan_build"] | None = Field(
        default=None,
        description=(
            "Plan mode only: advice = in-depth question, life_review = analysis of sleep/activity/nutrition/body/recovery "
            "quality, plan_build = create a training plan. Leave empty in normal chat."
        ),
    )
    meal_log: list[MealLog] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Only for LOG_FOOD: one entry per meal the user reports (separate meals for different times), each with "
            "its foods. Leave empty for any other intent."
        ),
    )
    create_distinct: SkipJsonSchema[bool] = False
    read_only: SkipJsonSchema[bool] = False


class AgentState(TypedDict, total=False):
    # Chế độ trò chuyện người dùng chọn ('normal' | 'plan'); vắng mặt ở checkpoint cũ (xem services/mode.py).
    mode: str
    # Chế độ thường gặp câu hỏi tư vấn: mời người dùng hỏi lại ở chế độ này.
    suggested_mode: str | None
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
    # Lượt trước đã hỏi qua một form, nên tin nhắn này là câu trả lời cho form đó chứ không mở yêu cầu mới.
    replying_to_form: bool
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
    # Ngữ cảnh cá nhân (do code quản lý): thẻ ngữ cảnh của người dùng cho lượt chạy này, việc các lần đọc sâu
    # của chủ đề đã chạy hay chưa, bằng chứng tra cứu cho câu trả lời cá nhân hoá và vết định tuyến.
    user_context: dict[str, Any] | None
    user_context_run_id: str | None
    personal_reads_done: bool
    research_evidence: dict[str, Any] | None
    route_trace: list[dict[str, Any]]
