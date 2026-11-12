"""Các luật code chạy sau lời gọi model định tuyến trong OrchestrationAgent.decide.

Mỗi luật nhận quyết định của router (RouteDecision, sửa tại chỗ như trước) và ngữ cảnh chỉ đọc của bước định tuyến;
trả Applied khi luật có tác dụng, None khi không. `POST_ROUTER` giữ đúng thứ tự xét luật trước đây trong decide;
`run` chạy lần lượt danh sách, ghi vết từng luật vào route_trace như cũ và gom kết quả phụ (form, thẻ món thiếu, lời
mời sang chế độ Plan, nhiệm vụ song song) cho decide dựng kết quả định tuyến.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, NamedTuple

from agentic.agents.specialists import BY_NAME
from agentic.agents.state import RouteDecision
from agentic.core import roster
from agentic.core.context import request_context
from agentic.research.contracts import QA_INTENTS
from agentic.security.input_guard import safe_query
from agentic.services import delegation, food_gap, food_suggestion, mode, personal_context
from agentic.tools.policy import CATALOG_DEPENDENCIES, TRAINING_DOMAINS, needs_catalog_handoff

PERSONAL_MEASURE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:kg|cm|tuổi|tuoi|kcal|bpm)\b", re.I)
# Yêu cầu cá nhân hoá vẫn tra cứu tri thức: mỗi chủ đề một ý định QA cho kế hoạch tra cứu.
TOPIC_INTENTS = {"nutrition": "FOOD_KNOWLEDGE_QA", "body": "FOOD_KNOWLEDGE_QA"}
READ_ANSWER = "Trả lời theo dữ liệu backend đã đọc; nếu catalog trống, nêu chưa có kết quả."


@dataclass(frozen=True)
class RouteContext:
    """Ngữ cảnh chỉ đọc của một bước định tuyến."""

    state: dict
    policy: mode.ModePolicy
    request: str
    # Thẻ ngữ cảnh cá nhân của lượt (None khi chế độ không nạp thẻ hoặc backend không dựng được).
    card: dict | None
    # Quyết định trước đó của lượt: quyền chỉ-đọc của lần đọc nhanh/Jev không được LLM nâng lên.
    read_policy: dict
    # Bước định tuyến đầu tiên của lượt chạy.
    first: bool
    # Đánh giá an toàn không chặn của yêu cầu, hoặc None.
    verdict: Any
    parallel: bool
    # Kết quả phụ các luật trước đã trả trong lần chạy danh sách này.
    outputs: Mapping = field(default_factory=dict)


class Applied(NamedTuple):
    decision: RouteDecision
    # Tên luật (vết dựng từ quyết định sau luật), một mục vết đầy đủ, hoặc None khi luật không ghi vết.
    trace: str | dict | None = None
    # Kết quả phụ: "form" (form, lời dẫn), "gap" (thẻ món thiếu), "redirect" (mời sang Plan), "delegated" (nhiệm vụ).
    outputs: dict | None = None


def run(rules, decision, ctx):
    """(quyết định, các mục vết, kết quả phụ) sau khi xét lần lượt các luật."""
    trace, outputs = [], {}
    for rule in rules:
        applied = rule(decision, ctx)
        if applied is None:
            continue
        decision = applied.decision
        if isinstance(applied.trace, str):
            trace.append(
                {
                    "stage": "rule",
                    "rule": applied.trace,
                    "action": decision.action,
                    "domain": decision.domain,
                }
            )
        elif applied.trace:
            trace.append(applied.trace)
        if applied.outputs:
            outputs.update(applied.outputs)
            ctx = replace(ctx, outputs=MappingProxyType(dict(outputs)))
    return decision, trace, outputs


def hitl_requested(decision):
    """Router hỏi lại có cấu trúc: action clarify kèm thông tin còn thiếu. Đây là hợp đồng HITL của lượt: trạng thái
    needs_input và một thẻ hỏi; không luật tư vấn, cá nhân hoá hay tra cứu nào được đổi nó thành câu trả lời."""
    return decision.action == "clarify" and bool(decision.missing_fields)


def public_question(request):
    """Câu hỏi của người dùng dưới dạng truy vấn tra cứu công khai, hoặc None khi vẫn chứa dữ liệu riêng."""
    # Số đo của chính người dùng ("giảm 3 kg", "nặng 70 kg") không bao giờ bị gửi đi thành truy vấn tra cứu.
    public = PERSONAL_MEASURE.sub("", request).strip()[:180]
    try:
        return safe_query(public, request_context.get().private_values)
    except (ValueError, LookupError):
        return None


def research_plan(decision, request, *, researched=False, deep=False):
    """Yêu cầu cá nhân hoá tra cứu câu hỏi công khai của nó (một lần mỗi lượt) khi câu hỏi đó có thể
    diễn đạt mà không cần chi tiết cá nhân; nếu không, chỉ trả lời từ dữ liệu của người dùng."""
    if hitl_requested(decision):
        # Hợp đồng HITL: router đã nêu thông tin cần hỏi lại; tư vấn hay tra cứu không bao giờ thay câu hỏi đó.
        return
    # Không có gì cụ thể để tra cứu (chủ đề "general"): trả lời từ thẻ ngữ cảnh và cuộc trò chuyện.
    # Chủ đề "general" chỉ được tra cứu ở chế độ Plan (deep), nơi mọi câu tư vấn đều cần nguồn.
    researched = researched or (decision.topic == "general" and not deep)
    query = None if researched else decision.research_query
    if not query and not researched:
        query = public_question(request)
    if not query:
        decision.action, decision.next_agent = "answer", "orchestrator"
        return
    decision.research_query = query
    if decision.intent not in QA_INTENTS:
        decision.intent = TOPIC_INTENTS.get(decision.topic, "SPORTS_KNOWLEDGE_QA")
    decision.action, decision.next_agent = "research", "research"


def asks_first(task, state, request):
    """Agent của nhiệm vụ cần người dùng chọn trước khi làm (ví dụ cách ghi buổi gym)."""
    probe = RouteDecision(
        intent=task["intent"],
        action="tool",
        next_agent="tool",
        domain=task["domain"],
        instruction=task["instruction"],
    )
    return (
        BY_NAME[roster.specialist_for(task["domain"])].preflight(probe, state, request)
        is not None
    )


# ---------------------------------------------------------------- luật sau router, theo thứ tự xét


def primary_task_domain(decision, ctx):
    primary = next((task.domain for task in decision.tasks if task.domain), None)
    if decision.action == "tool" and not decision.domain and primary:
        # Tin nhắn nhiều ý có thể không có một miền chung: phần đầu tiên là tuyến tuần tự dự phòng.
        decision.domain = primary
        return Applied(decision, "primary_task_domain")
    return None


def read_only_policy(decision, ctx):
    """Một lần LLM tiếp tục sau đó không thể nâng quyền của một lần đọc Jev (không ghi vết)."""
    if not ctx.read_policy.get("read_only"):
        return None
    decision.read_only = True
    if decision.action == "research" or (
        decision.action == "tool" and decision.domain != ctx.read_policy.get("domain")
    ):
        decision.action, decision.next_agent = "answer", "orchestrator"
        decision.domain = ctx.read_policy.get("domain")
        decision.instruction = READ_ANSWER
    return Applied(decision)


def clarify_to_catalog_lookup(decision, ctx):
    if decision.action == "clarify" and needs_catalog_handoff(
        decision.domain, " ".join(decision.missing_fields) + " " + decision.instruction
    ):
        decision.action, decision.next_agent = "tool", "tool"
        decision.instruction = (
            "Tự tra catalog theo tên; không yêu cầu ID người dùng. " + decision.instruction
        )
        return Applied(decision, "clarify_to_catalog_lookup")
    return None


def clarify_known_facts(decision, ctx):
    if (
        decision.action == "clarify"
        and ctx.card
        and decision.missing_fields
        and all(
            personal_context.answered_by_card(field, ctx.card) for field in decision.missing_fields
        )
    ):
        # Hỏi những thông tin HercFit đã lưu thì không bao giờ là một câu hỏi làm rõ.
        decision.action, decision.next_agent, decision.missing_fields = (
            "answer",
            "orchestrator",
            [],
        )
        return Applied(decision, "clarify_known_facts")
    return None


def personalization(decision, ctx):
    """plan_deep (chế độ Plan) hoặc personalize; ngoài hai luật này yêu cầu không cá nhân hoá. Đây là một khối
    if/elif/else: điều kiện của cả hai luật tính trên cùng một quyết định, trước khi luật nào sửa nó."""
    request = ctx.request
    personal = not decision.read_only and personal_context.wants_personal_context(
        request, decision.model_dump()
    )
    if not ctx.policy.deep:
        decision.plan_task = None
    deep = (
        ctx.policy.deep
        and not decision.read_only
        and decision.intent not in personal_context.NON_ADVICE_INTENTS
        and (
            personal
            or decision.plan_task is not None
            or decision.intent in QA_INTENTS
            or (
                decision.intent == "GENERAL_CHAT"
                and personal_context.knowledge_question(request)
            )
        )
    )
    researched = bool(ctx.state.get("research_count"))
    if deep:
        # Chế độ Plan: tư vấn, phân tích và lập kế hoạch luôn đọc dữ liệu người dùng rồi tra cứu, không chờ model đoán.
        decision.personalize = True
        if decision.plan_task == "life_review":
            decision.topic = "wellbeing"
        elif decision.plan_task == "plan_build":
            decision.intent, decision.domain = "TRAINING_PLAN", "training_plans"
            if decision.topic not in {"running", "strength", "training"}:
                guess = personal_context.topic_for(request)
                decision.topic = guess if guess in {"running", "strength"} else "training"
        decision.topic = decision.topic or personal_context.topic_for(request, decision.domain)
        if decision.action in {"clarify", "tool"} and not decision.missing_fields:
            decision.action, decision.next_agent = "answer", "orchestrator"
        research_plan(decision, request, researched=researched, deep=True)
        return Applied(decision, "plan_deep")
    if personal:
        # Tư vấn hoặc phân tích cho người dùng này: đọc dữ liệu của họ trước, rồi mới tra cứu tri thức.
        decision.personalize = True
        decision.topic = decision.topic or personal_context.topic_for(request, decision.domain)
        if decision.action in {"clarify", "tool"} and not decision.missing_fields:
            decision.action, decision.next_agent = "answer", "orchestrator"
        research_plan(decision, request, researched=researched)
        return Applied(decision, "personalize")
    decision.personalize, decision.topic = False, None
    return Applied(decision)


def chat_to_knowledge(decision, ctx):
    if not (
        decision.intent == "GENERAL_CHAT"
        and decision.action == "answer"
        and ctx.first
        and not decision.read_only
        and not decision.personalize
        and not ctx.state.get("research_count")
        and personal_context.knowledge_question(ctx.request)
    ):
        return None
    # Lưới an toàn: câu hỏi kiến thức thể thao/dinh dưỡng bị gọi là trò chuyện vẫn phải trả lời từ nguồn đã
    # kiểm chứng, không từ trí nhớ của model. Luật knowledge_to_research phía sau chuyển nó sang research.
    query = decision.research_query or public_question(ctx.request)
    if not query:
        return None
    decision.intent = TOPIC_INTENTS.get(
        personal_context.topic_for(ctx.request), "SPORTS_KNOWLEDGE_QA"
    )
    decision.research_query = query
    return Applied(decision, "chat_to_knowledge")


def training_read_first(decision, ctx):
    if (
        decision.domain in TRAINING_DOMAINS
        and not decision.personalize
        and (
            (decision.action == "clarify" and not decision.missing_fields)
            or (decision.action == "research" and decision.intent not in QA_INTENTS)
        )
    ):
        # Câu trả lời về tập luyện lấy từ phân tích của backend: đọc trước khi hỏi hoặc tìm trên web.
        decision.action, decision.next_agent = "tool", "tool"
        return Applied(decision, "training_read_first")
    return None


def plan_catalog_only(decision, ctx):
    if decision.intent == "TRAINING_PLAN" and decision.domain == "exercises":
        # Lịch tập chỉ dùng bài có sẵn trong catalog: miền lịch tập đọc catalog, không tạo bài mới hay tra web.
        decision.domain = "training_plans"
        if decision.action == "research":
            decision.action, decision.next_agent = "tool", "tool"
        return Applied(decision, "plan_catalog_only")
    return None


def tool_next_agent(decision, ctx):
    if decision.action == "tool" and decision.domain and decision.next_agent != "tool":
        # Hành động quyết định; nhãn next_agent không khớp được chuẩn hoá.
        decision.next_agent = "tool"
        return Applied(decision, "tool_next_agent")
    return None


def require_tool_domain(decision, ctx):
    """Chốt chặn: tuyến tool phải có miền (không phải luật, không ghi vết)."""
    if decision.action == "tool" and not decision.domain:
        raise ValueError("Invalid tool route")
    return None


def knowledge_to_research(decision, ctx):
    if not (
        decision.intent in QA_INTENTS
        and not decision.read_only
        and not decision.personalize
        and decision.action in {"answer", "research"}
    ):
        return None
    # Câu trả lời tri thức lấy từ nguồn đã kiểm chứng, không từ trí nhớ của model. Một tuyến tool
    # (ví dụ tạo hoặc đọc lịch tập của người dùng) vẫn là tuyến tool.
    # Yêu cầu cá nhân hoá đã được lập kế hoạch bởi research_plan ở luật personalization.
    # Vết ghi hành động trước khi luật đổi nó (như trước đây); router đã chọn research thì không ghi vết.
    trace = None
    if decision.action != "research":
        trace = {
            "stage": "rule",
            "rule": "knowledge_to_research",
            "action": decision.action,
            "domain": decision.domain,
        }
    decision.action, decision.next_agent = "research", "research"
    return Applied(decision, trace)


def catalog_research(decision, ctx):
    """food_gap_card hoặc food_research_to_catalog cho tra cứu catalog món ăn; bài tập đi research (không ghi vết)."""
    if decision.action != "research" or decision.intent in QA_INTENTS:
        return None
    # Tra cứu catalog giải quyết catalog trước (ưu tiên database) trong bước lập kế hoạch. Một miền
    # nhật ký ("ghi đồ uống này" -> meals) tra cứu catalog mà nó phụ thuộc.
    decision.domain = CATALOG_DEPENDENCIES.get(decision.domain, decision.domain)
    decision.next_agent = "research"
    if decision.domain not in {"foods", "exercises"}:
        raise ValueError("Research is restricted to food and exercises")
    if decision.domain != "foods":
        return Applied(decision)
    # Món ăn không tra web: có bản nháp bữa thì đường nhanh tra catalog và hỏi bằng thẻ món thiếu;
    # chỉ có tên món thì hỏi thẳng bằng thẻ (tìm món hoặc tạo món riêng).
    query = (decision.research_query or "").strip()
    decision.intent, decision.research_query = "LOG_FOOD", None
    if query and not decision.meal_log:
        decision.action, decision.next_agent = "answer", "orchestrator"
        gap = food_gap.ask([food_gap.gap_item("q:0", query)])
        return Applied(decision, "food_gap_card", {"gap": gap})
    decision.action, decision.next_agent, decision.domain = "tool", "tool", "meals"
    return Applied(decision, "food_research_to_catalog")


def read_only_recheck(decision, ctx):
    """Các luật phía trên có thể biến một câu hỏi làm rõ thành yêu cầu tool, nên kiểm tra lại miền của lần đọc
    chỉ-đọc sau tất cả các phép biến đổi tuyến cơ sở (không ghi vết)."""
    if (
        ctx.read_policy.get("read_only")
        and decision.action == "tool"
        and decision.domain != ctx.read_policy.get("domain")
    ):
        decision.action, decision.next_agent = "answer", "orchestrator"
        decision.domain = ctx.read_policy.get("domain")
        decision.instruction = READ_ANSWER
        return Applied(decision)
    return None


def food_suggestion_lookup(decision, ctx):
    """Do code quyết định: gợi ý bữa ăn không bao giờ được trả lời trước khi tra catalog (không ghi vết)."""
    if (
        decision.action == "answer"
        and not decision.personalize
        and food_suggestion.is_food_suggestion(ctx.request)
        and not food_suggestion.catalog_read_this_turn(ctx.state)
        and (not ctx.read_policy.get("read_only") or ctx.read_policy.get("domain") == "foods")
    ):
        return Applied(RouteDecision.model_validate(food_suggestion.lookup_decision()))
    return None


def plan_mode_only(decision, ctx):
    redirect = (
        ctx.policy.name == mode.NORMAL
        and not decision.read_only
        and (
            decision.personalize
            or (decision.action == "research" and decision.intent in QA_INTENTS)
            or (
                decision.action in {"tool", "clarify"}
                and bool(decision.domain)
                and not ctx.policy.allows(decision.domain)
            )
        )
    )
    if not redirect:
        return None
    # Chế độ ghi nhanh không tư vấn từ trí nhớ của model: mời người dùng hỏi lại ở chế độ Plan.
    decision.action, decision.next_agent, decision.missing_fields = "answer", "orchestrator", []
    decision.personalize, decision.topic = False, None
    return Applied(decision, "plan_mode_only", {"redirect": True})


def owner_preflight(decision, ctx):
    """Agent nhận tuyến cần người dùng chọn trước (ví dụ cách ghi buổi gym): hỏi bằng form do code dựng; tên luật
    do agent đặt (gym_mode_guard)."""
    owner = BY_NAME.get(roster.specialist_for(decision.domain))
    checked = owner.preflight(decision, ctx.state, ctx.request) if owner else None
    if not checked:
        return None
    form, form_reply, name = checked
    return Applied(decision, name, {"form": (form, form_reply)})


def fan_out(decision, ctx):
    if not (
        ctx.first
        and decision.action == "tool"
        and "form" not in ctx.outputs
        and "redirect" not in ctx.outputs
        and ctx.verdict is None
        and not ctx.state.get("replying_to_form")
        and not decision.read_only
        and not decision.personalize
        and decision.intent not in QA_INTENTS
        and ctx.parallel
    ):
        return None
    # Tin nhắn nhiều ý: mỗi phần giao cho agent sở hữu miền của nó, chạy song song (services/delegation.py).
    delegated = delegation.plan(decision.model_dump(), ctx.policy)
    if delegated and any(asks_first(task, ctx.state, ctx.request) for task in delegated):
        delegated = None  # một phần cần người dùng chọn trước (form): đi đường tuần tự
    if not delegated:
        return None
    trace = {
        "stage": "rule",
        "rule": "fan_out",
        "action": "delegate",
        "domain": None,
        "agents": [roster.specialist_for(task["domain"]) for task in delegated],
    }
    return Applied(decision, trace, {"delegated": delegated})


# Thứ tự là hợp đồng: mỗi luật thấy quyết định đã qua các luật đứng trước.
POST_ROUTER = (
    primary_task_domain,
    read_only_policy,
    clarify_to_catalog_lookup,
    clarify_known_facts,
    personalization,
    chat_to_knowledge,
    training_read_first,
    plan_catalog_only,
    tool_next_agent,
    require_tool_domain,
    knowledge_to_research,
    catalog_research,
    read_only_recheck,
    food_suggestion_lookup,
    plan_mode_only,
    owner_preflight,
    fan_out,
)
