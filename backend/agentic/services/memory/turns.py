"""Bản tóm tắt có cấu trúc của một lượt hội thoại cho knowledge graph.

Chỉ giữ dữ kiện định tuyến: miền/hành động của quyết định đầu tiên, các tool đã
chạy, có ghi hoặc yêu cầu ghi không, trạng thái cuối và vết định tuyến chỉ gồm
nhãn. Tin nhắn, câu trả lời, tham số tool và văn bản ý định tự do của model
không bao giờ ra ngoài. Knowledge graph chỉ chiếu các trường Run của riêng nó.
"""

from agentic.knowledge_graph.intents import classify
from agentic.knowledge_graph.service import render_lines
from agentic.research.contracts import Intent
from agentic.tools.registry import REGISTRY

# Nhãn tuyến giữ trong vết; mọi ý định khác do model viết được ghi là OTHER.
ROUTE_INTENTS = {i.value for i in Intent} | {
    "BODY_REVIEW",
    "ACTIVITY_REVIEW",
    "SLEEP_REVIEW",
    "RECOVERY_REVIEW",
    "ENERGY_BALANCE",
    "PROFILE_REVIEW",
    "PROFILE_UPDATE",
    "READ",
    "SAFETY",
    "clarification",
    "error",
    "limit",
    "catalog_lookup",
    "catalog_research",
    "catalog_estimate",
}


def route_summary(state):
    """Lượt được định tuyến thế nào: nhãn của router, các luật code đã thay đổi chúng, các lần đọc
    ngữ cảnh cá nhân và kết quả tra cứu. Chỉ nhãn và cờ, không bao giờ có văn bản."""
    trace = state.get("route_trace") or []

    def labels(step):
        if not step:
            return None
        intent = step.get("intent")
        return {
            "intent": intent if intent in ROUTE_INTENTS else "OTHER",
            "action": step.get("action"),
            "domain": step.get("domain"),
            "personalize": bool(step.get("personalize")),
            "topic": step.get("topic"),
        }

    def last(stage):
        return next((step for step in reversed(trace) if step.get("stage") == stage), None)

    context, research = last("context"), last("research")
    card = state.get("user_context")
    return {
        "router": labels(next((step for step in trace if step.get("stage") == "router"), None)),
        "rules": [step["rule"] for step in trace if step.get("stage") == "rule"][:12],
        # Các agent chuyên trách supervisor đã giao việc, theo thứ tự.
        "agents": [step["agent"] for step in trace if step.get("stage") == "agent"][:8],
        "final": labels(last("final")),
        "user_context": {
            "loaded": bool(card),
            "missing": list(card.get("missing") or [])[:10] if card else [],
        },
        "context_reads": [
            {"tool": read["tool"], "ok": read["ok"]} for read in (context or {}).get("reads", [])
        ][:8],
        "research": {
            k: research.get(k)
            for k in ("status", "retrieval", "documents", "claims", "verified", "error_code")
            if research.get(k) is not None
        }
        if research
        else None,
        "kg": graph_summary(state),
    }


def graph_summary(state):
    """Những gì knowledge graph cung cấp cho lượt này: trạng thái, miền, mục và số đếm, không bao giờ có dữ kiện."""
    retrieval = (
        (state.get("telemetry") or {}).get("retrieval")
        if (state.get("telemetry") or {}).get("run_id") == state.get("run_id")
        else None
    )
    if not retrieval:
        return None
    context = (
        state.get("graph_context")
        if state.get("graph_context_run_id") == state.get("run_id")
        else None
    )
    lines = render_lines(context) if context else []
    return {
        "status": retrieval.get("status"),
        "statuses": list(retrieval.get("statuses") or [])[:6],
        "attempts": retrieval.get("attempts", 1),
        "duration_ms": retrieval.get("duration_ms"),
        "domains": list((context or {}).get("domains") or retrieval.get("domains") or [])[:8],
        "sections": [section for section in (context or {}).get("sections") or []][:12],
        "facts": len((context or {}).get("facts") or []),
        "episodes": len((context or {}).get("episodes") or []),
        # Đếm theo dòng, không theo byte: nhãn ngày ("hôm nay") đổi theo đồng hồ, nên một bản ghi
        # dựng lại từ cùng checkpoint khi đối soát không được trông khác đi.
        "lines": len(lines),
    }


TERMINAL = {"completed", "needs_input", "pending_confirmation", "failed"}


def turn_record(state):
    run_id, status = state.get("run_id"), state.get("status")
    if not run_id or status not in TERMINAL:
        return None
    first = state.get("turn") or {}
    if first.get("run_id") != run_id:
        first = {}
    last = state.get("decision") or {}
    domain = first.get("domain") or last.get("domain")
    records = [record for record in state.get("execution_records") or [] if record.get("tool")]
    wrote = bool(state.get("pending_action")) or any(
        getattr(REGISTRY.get(record["tool"]), "write", False)
        and record.get("status") == "succeeded"
        for record in records
    )
    researched = bool(state.get("research_count")) or first.get("action") == "research"
    refs = []
    for record in records:
        for ref in record.get("resource_refs") or []:
            if ref not in refs:
                refs.append(ref)
    return {
        "run_id": run_id,
        "session_id": state.get("session_id"),
        "domain": domain,
        "intent": classify(
            domain, first.get("intent") or last.get("intent"), wrote=wrote, researched=researched
        ),
        "action": first.get("action") or last.get("action"),
        "status": status,
        "tools": sorted({record["tool"] for record in records})[:8],
        "resource_refs": refs[:10],
        "route": route_summary(state),
    }
