"""Giai đoạn truy hồi graph có giới hạn; ResearchV2 kết hợp các giai đoạn RAG trên tài liệu.

Sự cố knowledge graph hạ xuống đường backend/model hiện có. Không kết quả truy hồi
nào có thể cấp quyền dùng tool hay đổi danh tính đã xác thực của request.
"""

import asyncio
from time import perf_counter

from agentic.core.context import request_context
from agentic.knowledge_graph.service import PILOT_DOMAINS
from agentic.observability import annotate
from agentic.observability.telemetry import active_metrics, merge_retrieval
from agentic.services import personal_context
from agentic.services.routing import latest_request

# Các chủ đề ngữ cảnh cá nhân (services.personal_context.TOPICS) và miền graph chứa dữ liệu của chúng.
TOPIC_DOMAINS = {
    "running": "trainings",
    "strength": "trainings",
    "training": "trainings",
    "nutrition": "meals",
    "body": "metrics",
    "recovery": "recovery",
    "wellbeing": "recovery",
}


def decision_domains(decision):
    """Các miền graph do một quyết định định tuyến gọi tên: miền của nó và chủ đề cá nhân của nó."""
    decision = decision or {}
    return [
        d
        for d in dict.fromkeys([decision.get("domain"), TOPIC_DOMAINS.get(decision.get("topic"))])
        if d in PILOT_DOMAINS
    ]


async def retrieve_graph_context(state, domains, *, settings, graph_context=None):
    fresh = state.get("graph_context_run_id") == state.get("run_id")
    covered = list(state.get("graph_context_domains") or []) if fresh else []
    wanted = [d for d in dict.fromkeys([*covered, *domains]) if d in PILOT_DOMAINS]
    # Chỉ truy hồi lại khi định tuyến chạm tới một miền mà gợi ý đầu tiên bỏ sót. Khi không có
    # service graph được dựng (baseline đánh giá offline) hoặc nguồn kg_facts bị tắt thì không có gì để đọc.
    if (
        graph_context is None
        or "kg_facts" not in personal_context.sources(settings)
        or not set(wanted) - set(covered)
    ):
        return {}
    # Một miền chỉ được tính là đã phủ sau một lần đọc thành công, để timeout được thử lại sau trong lượt chạy.
    update = {
        "graph_retrieval_attempted": True,
        "graph_context_run_id": state.get("run_id"),
        "graph_context_domains": covered,
        "graph_context": state.get("graph_context") if fresh else None,
    }
    started = perf_counter()
    status = "unavailable"
    try:
        ctx = request_context.get()
        if ctx.user_id != state["user_id"]:
            status = "blocked"
        else:
            timeout = min(getattr(settings, "KG_RETRIEVAL_TIMEOUT_MS", 150), 150) / 1000
            context = await asyncio.wait_for(
                graph_context.retrieve(
                    authenticated_user_id=ctx.user_id,
                    session_id=state["session_id"],
                    message=latest_request(state),
                    domain_hint=wanted,
                ),
                timeout=timeout,
            )
            data = context.model_dump(mode="json")
            status = data.get("status", "unavailable")
            if status in {"ok", "empty"}:
                update["graph_context_domains"] = wanted
                update["graph_context"] = data
    except TimeoutError:
        status = "timeout"
    except Exception:
        # Sự cố KG không bao giờ biến một workflow backend/LLM dùng được thành thất bại.
        status = "unavailable"
    duration = round((perf_counter() - started) * 1000, 3)
    metrics = active_metrics.get()
    if metrics is not None:
        # Một node có thể đọc hai lần (gợi ý từ request, rồi miền của router): giữ cả hai lần thử.
        metrics["retrieval"] = merge_retrieval(
            metrics.get("retrieval"), {"status": status, "duration_ms": duration, "domains": wanted}
        )
    annotate(status=status, duration_ms=duration)
    return update
