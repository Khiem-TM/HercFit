from typing import Annotated, Any, Literal, get_args
from typing_extensions import TypedDict
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema # Loại bỏ trường khỏi JSON schema
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

def collect_results(left, right):
    """Reducer của agent_results: các nhánh song song cùng cộng dồn; None (do join trả về) đặt lại danh sách."""
    return [] if right is None else [*(left or []), *right]


Domain = Literal['profile', 'metrics', 'goals', 'meals', 'trainings', 'foods', 'exercises', 'progress', 'training_plans', 'coaching', 'health']

class MealLogItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    food: str = Field(max_length=80, description='Food name exactly as the user said it, without quantity words')
    quantity: float | None = Field(default=None, gt=0, le=5000,
                                   description='Amount the user stated; null when they did not say how much')
    unit: Literal['SERVING', 'G', 'ML'] | None = Field(
        default=None, description='SERVING for counted portions (cái, bát, tô, đĩa, suất, ly, cốc, phần, quả); '
                                  'G or ML only when the user gave grams/millilitres; null when unknown')


class MealLog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, max_length=120, description='Short meal name, e.g. Bữa sáng, Bữa trưa')
    consumed_at: str | None = Field(default=None, description='ISO 8601 time with offset, resolved from the current time '
                                                              '(sáng nay, trưa nay, vừa xong); null when unknown')
    items: list[MealLogItem] = Field(default_factory=list, max_length=5)


class AgentTask(BaseModel):
    """Một phần độc lập của tin nhắn nhiều ý, giao cho agent chuyên trách sở hữu miền của nó (chạy song song).

    Không ràng buộc nào ở đây được làm hỏng cả quyết định định tuyến: miền lạ thành None (lượt đi tuần tự)."""
    model_config = ConfigDict(extra='ignore')
    domain: Domain | None = None
    intent: str = Field(default='', description='Label of this part, e.g. LOG_FOOD, LOG_EXERCISE, BODY_REVIEW')
    instruction: str = Field(default='', description='Only this part of the request, as a concrete task')

    @field_validator('domain', mode='before')
    @classmethod
    def known_domain(cls, value):
        return value if value in get_args(Domain) else None


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
    personalize: bool = Field(default=False, description="Advice or analysis about this user's own body/training/nutrition: read their stored data first")
    topic: Literal['running', 'strength', 'training', 'nutrition', 'body', 'recovery', 'wellbeing', 'general'] | None = Field(
        default=None, description='Subject of a personalized request; selects which stored analytics are read')
    plan_task: Literal['advice', 'life_review', 'plan_build'] | None = Field(default=None, description=(
        'Plan mode only: advice = in-depth question, life_review = analysis of sleep/activity/nutrition/body/recovery '
        'quality, plan_build = create a training plan. Leave empty in normal chat.'))
    meal_log: list[MealLog] = Field(default_factory=list, max_length=4, description=(
        'Only for LOG_FOOD or a LOG_FOOD task: one entry per meal the user reports (separate meals for different '
        'times), each with its foods. Leave empty otherwise.'))
    tasks: list[AgentTask] = Field(default_factory=list, description=(
        'Only when one new message combines 2-3 independent requests in different areas (e.g. log a meal AND log a '
        'workout AND read body/activity data): one task per part, run in parallel. Leave empty for a single request, '
        'a follow-up or form answer, or when any part is a knowledge/advice question.'))
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
    # Giao việc song song (services/delegation.py): kết quả từng nhánh agent cộng dồn qua reducer, nút join gộp rồi
    # đặt lại; các bản xem trước còn lại chờ thẻ xác nhận của chúng, từng thẻ một.
    agent_results: Annotated[list[dict[str, Any]], collect_results]
    pending_queue: list[dict[str, Any]]
