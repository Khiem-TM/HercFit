"""Lỗi node, độ trễ, số liệu sử dụng model và tính phí JEV nhất quán trên toàn graph."""

import logging
from time import perf_counter

from openai import AuthenticationError

from agentic.core.app.config import AgentSettings
from agentic.observability import annotate
from agentic.observability.telemetry import active_metrics, merge_jev_metrics, merge_retrieval

logger = logging.getLogger(__name__)


async def run_node(fn, state, node, settings: AgentSettings):
    started = perf_counter()
    metrics = {}
    marker = active_metrics.set(metrics)
    try:
        from agentic.observability.node_span import span

        with span(node, state.get("run_id")):
            result = await fn(state)
    except Exception as exc:
        # Exception có thể chứa body request phía trên. Chỉ lộ ra tên lớp;
        # không bao giờ ghi nội dung exception thô vào log vận hành.
        logger.warning("agent_node_failed node=%s error_type=%s", node, type(exc).__name__)
        annotate(status="failed", error_code=type(exc).__name__)
        result = {
            "status": "failed",
            "error": "Không hoàn tất bước xử lý (" + type(exc).__name__ + ").",
        }
        if (
            isinstance(exc, AuthenticationError)
            or type(exc).__name__ == "OpenAIAuthenticationError"
        ):
            provider = settings.DEFAULT_PROVIDER
            result.update(
                model_auth_failed=True,
                error=f"Không xác thực được model ({provider}). Kiểm tra khóa API của nhà cung cấp trong cấu hình agent và khởi động lại dịch vụ.",
            )
    finally:
        active_metrics.reset(marker)
    previous = state.get("telemetry") or {}
    telemetry = (
        dict(previous)
        if previous.get("run_id") == state.get("run_id")
        else {"run_id": state.get("run_id")}
    )
    if telemetry.get("llm_calls") and not telemetry.get("billing_version"):
        # Checkpoint được tiếp tục từ trước khi có đo đạc tính phí không có
        # độ đầy đủ giá/số liệu sử dụng lịch sử đã kiểm chứng; không bao giờ coi chúng là miễn phí.
        telemetry["llm_cost_unknown_calls"] = (
            telemetry.get("llm_cost_unknown_calls", 0) + telemetry["llm_calls"]
        )
        telemetry["llm_usage_unknown_calls"] = (
            telemetry.get("llm_usage_unknown_calls", 0) + telemetry["llm_calls"]
        )
    telemetry["billing_version"] = 1
    for key in (
        "llm_calls",
        "input_tokens",
        "output_tokens",
        "model_ms",
        "llm_cost",
        "llm_cost_unknown_calls",
        "llm_usage_unknown_calls",
    ):
        telemetry[key] = telemetry.get(key, 0) + metrics.get(key, 0)
    merge_jev_metrics(telemetry, metrics.get("jev_events", []))
    telemetry["nodes"] = [
        *telemetry.get("nodes", []),
        {
            "name": node,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "llm_calls": metrics.get("llm_calls", 0),
        },
    ][-settings.MAX_GRAPH_STEPS :]
    if "retrieval" in metrics:
        telemetry["retrieval"] = merge_retrieval(telemetry.get("retrieval"), metrics["retrieval"])
    result["telemetry"] = telemetry
    decision = result.get("decision") or {}
    annotate(
        node=node,
        domain=decision.get("domain") or (state.get("decision") or {}).get("domain"),
        research=node == "research" or bool(state.get("research_count")),
    )
    if result.get("status") == "failed":
        annotate(status="failed", error_code="NodeFailed")
    return result
