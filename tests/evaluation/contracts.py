"""Hợp đồng eval thống nhất, độc lập nhà cung cấp (không phụ thuộc định dạng nội bộ của Langfuse hay Ragas).

Mọi bộ eval (agent, safety, RAG, KG, JEV, memory, personalization, Daily Health, hiệu năng) đều quy về các bản ghi
dưới đây; báo cáo, cổng chất lượng, so sánh baseline và đồng bộ Langfuse chỉ đọc hợp đồng này. Module chỉ phụ thuộc
Pydantic để môi trường chấm Ragas riêng (xem `ragas_scoring.py`) cũng import được.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

GateKind = Literal["hard_safety", "quality", "info"]
ScoreType = Literal["NUMERIC", "BOOLEAN", "CATEGORICAL"]
RunStatus = Literal["pass", "fail", "safety_fail", "error", "blocked"]
ErrorCategory = Literal[
    "routing",
    "tool_selection",
    "tool_arguments",
    "trajectory",
    "confirmation",
    "authorization",
    "state",
    "safety",
    "retrieval",
    "generation",
    "provider",
    "timeout",
    "infrastructure",
    "evaluator",
    "other",
]
# Mã thoát chung của mọi runner (CI đọc được không cần phân tích báo cáo).
EXIT_CODES = {"pass": 0, "fail": 1, "safety_fail": 2, "error": 3, "blocked": 4}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetInfo(Model):
    name: str
    version: str
    fingerprint: str = Field(description="sha256 của nội dung chuẩn hoá các ca đã chọn")
    path: str | None = None
    case_count: int
    split: str | None = None


class EvaluationCase(Model):
    id: str
    suite: str
    input: dict[str, Any]
    reference: dict[str, Any] = Field(
        default_factory=dict,
        description="Đầu ra/hành vi kỳ vọng do người xem xét viết, không do LLM sinh",
    )
    tags: list[str] = Field(default_factory=list)
    split: str | None = None
    severity: Literal["critical", "high", "normal"] = "normal"
    modes: list[Literal["deterministic", "live"]] = Field(default_factory=lambda: ["deterministic"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorRecord(Model):
    category: ErrorCategory
    code: str
    message: str | None = None


class TokenUsage(Model):
    llm_calls: int = 0
    llm_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = Field(
        default=None, description="None khi chưa có giá đã kiểm chứng; không bao giờ là 0 giả"
    )
    cost_status: Literal["configured", "unknown"] = "unknown"


class ToolExecutionRecord(Model):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: str = Field(
        description="ok | pending_confirmation | not_allowed | backend_error | ..."
    )
    ok: bool | None = None
    is_write: bool = False
    requires_confirmation: bool = False
    action_id: str | None = None
    approved: bool | None = None
    executed: bool = False
    status_code: int | None = None
    error: str | None = None
    idempotency_key: str | None = None
    acting_user: str | None = Field(
        default=None, description="Người dùng mà backend thấy cho lời gọi này"
    )


class RetrievedContext(Model):
    doc_id: str
    chunk_id: str | None = None
    rank: int
    score: float | None = None
    text: str | None = None
    page: int | None = None
    page_end: int | None = None
    heading: str | None = None
    source: str | None = None


class RetrievalRecord(Model):
    case_id: str
    query: str
    queries: list[str] = Field(default_factory=list)
    variant: str = Field(
        description="vector | bm25 | hybrid | hybrid_rerank | hybrid_rerank_rewrite | ..."
    )
    candidates: list[RetrievedContext] = Field(
        default_factory=list, description="Ứng viên thô trước rerank"
    )
    reranked: list[RetrievedContext] = Field(default_factory=list)
    final_contexts: list[RetrievedContext] = Field(
        default_factory=list, description="Ngữ cảnh đưa cho LLM"
    )
    answer: str | None = None
    reference_answer: str | None = Field(
        default=None, description="Chỉ khi có đáp án do người kiểm chứng"
    )
    corpus_version: str | None = None
    index_version: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    status: str | None = None


class AgentExecutionRecord(Model):
    case_id: str
    run_id: str | None = None
    trace_id: str | None = None
    status: str
    reply: str | None = None
    route: str | None = Field(
        default=None, description="Agent/hành động mà graph giao việc ở quyết định đầu"
    )
    selected_agents: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    domain: str | None = None
    route_rules: list[str] = Field(
        default_factory=list, description="Luật code đã quyết định (route_trace)"
    )
    tools: list[ToolExecutionRecord] = Field(default_factory=list)
    confirmations: list[dict[str, Any]] = Field(default_factory=list)
    verified_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Trạng thái backend đọc lại sau lượt chạy, không phải lời agent tự nói",
    )
    safety: dict[str, Any] | None = None
    clarification: dict[str, Any] | None = None
    food_gap: dict[str, Any] | None = None
    retrieval: list[RetrievalRecord] = Field(default_factory=list)
    models: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    graph_version: str | None = None
    latency_ms: float | None = None
    ttft_ms: float | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    errors: list[ErrorRecord] = Field(default_factory=list)


class EvaluationScore(Model):
    case_id: str
    name: str
    value: float | bool | str | None
    data_type: ScoreType
    passed: bool | None = None
    gate: GateKind = "quality"
    explanation: str | None = None
    evaluator: str
    evaluator_version: str
    trace_id: str | None = None


class CaseResult(Model):
    case: EvaluationCase
    record: dict[str, Any] = Field(
        description="AgentExecutionRecord/RetrievalRecord hoặc hàng gốc của bộ eval cũ"
    )
    scores: list[EvaluationScore] = Field(default_factory=list)
    error: ErrorRecord | None = None
    repeat_index: int = 0
    duration_ms: float | None = None


class RunMetadata(Model):
    schema_version: str = SCHEMA_VERSION
    experiment_id: str
    experiment_name: str
    suite: str
    # deterministic/live: bộ agent; retrieval: RAG; calibration/holdout: JEV; offline_import: nhập kết quả cũ.
    mode: Literal["deterministic", "live", "retrieval", "calibration", "holdout", "offline_import"]
    dataset: DatasetInfo
    git_sha: str | None = None
    git_dirty: bool | None = None
    release: str | None = None
    environment: str | None = None
    models: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    graph_version: str | None = None
    rag_config: dict[str, Any] = Field(default_factory=dict)
    jev_config: dict[str, Any] = Field(default_factory=dict)
    judge_config: dict[str, Any] = Field(default_factory=dict)
    evaluator_versions: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime | None = None
    repeat: int = 1
    notes: list[str] = Field(default_factory=list)


class GateResult(Model):
    name: str
    kind: Literal["hard_safety", "quality", "regression"]
    metric: str
    threshold: float | None = None
    actual: float | None = None
    passed: bool
    justification: str | None = None
    explanation: str | None = None


class EvaluationRun(Model):
    metadata: RunMetadata
    results: list[CaseResult] = Field(default_factory=list)
    aggregates: dict[str, float | int | None] = Field(default_factory=dict)
    analyses: dict[str, Any] = Field(default_factory=dict)


class EvaluationReport(Model):
    schema_version: str = SCHEMA_VERSION
    metadata: RunMetadata
    status: RunStatus
    exit_code: int
    aggregates: dict[str, float | int | None] = Field(default_factory=dict)
    analyses: dict[str, Any] = Field(default_factory=dict)
    gates: list[GateResult] = Field(default_factory=list)
    baseline: dict[str, Any] | None = None
    failures: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


def now():
    return datetime.now(timezone.utc)


def fingerprint(rows):
    """sha256 ổn định của các ca (khoá sắp xếp, không phụ thuộc thứ tự dòng trong file)."""
    canonical = sorted(
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows
    )
    return hashlib.sha256("\n".join(canonical).encode()).hexdigest()


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def dataset_info(name, rows, *, version, path=None, split=None):
    return DatasetInfo(
        name=name,
        version=version,
        fingerprint=fingerprint(rows),
        path=str(path) if path else None,
        case_count=len(rows),
        split=split,
    )
