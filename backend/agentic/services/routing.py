"""Chính sách định tuyến KG do code quản lý. Dữ liệu graph không thể cấp quyền dùng tool."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

# Giữ export hiện được dùng bởi baseline evaluation.
from agentic.components.context_filter import model_graph_context as model_graph_context
from agentic.tools.registry import REGISTRY
from domains.analytics.schemas.progress import ProgressRead

TEMPLATE_ID = "progress.explicit_dates"
TEMPLATE_VERSION = 1
TIMEZONE = "Asia/Ho_Chi_Minh"


class FastReadPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    template_id: str = TEMPLATE_ID
    template_version: int = TEMPLATE_VERSION
    registry_fingerprint: str
    tool: str = "get_progress"
    # Tham số tool đã chuẩn hoá: ngày và múi giờ là chuỗi, số đếm (ngày) là số nguyên.
    arguments: dict[str, str | int]


def registry_fingerprint():
    specs = [
        {
            "name": s.name,
            "domain": s.domain,
            "method": s.method,
            "path": s.path,
            "schema": s.schema.model_json_schema(),
        }
        for _, s in sorted(REGISTRY.items())
    ]
    return hashlib.sha256(
        json.dumps(specs, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def latest_request(state):
    for message in reversed(state.get("messages", [])):
        if message.type == "human":
            return message.content if isinstance(message.content, str) else ""
    return ""


def fast_reads_enabled(settings):
    # Các mẫu tự phân tích request; chúng không đọc dữ liệu graph.
    return bool(getattr(settings, "FAST_READ_ENABLED", False))


def _progress_arguments(match, today):
    period = match[1]
    if period in {"hôm nay", "hôm qua"}:
        start = end = (today - timedelta(days=period == "hôm qua")).isoformat()
    else:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", period)
        start, end = dates[0], dates[-1]
    return {"start_date": start, "end_date": end, "timezone": TIMEZONE}


def _no_arguments(_match, _today):
    return {}


def _timezone_argument(_match, _today):
    return {"timezone": TIMEZONE}


@dataclass(frozen=True)
class FastTemplate:
    """Ngữ pháp toàn tin nhắn cho một lệnh đọc độc lập. Yêu cầu ghép hoặc ngầm định
    không bao giờ khớp, nên router LLM vẫn xử lý mọi thứ khác."""

    id: str
    version: int
    domain: str
    tool: str
    pattern: re.Pattern
    instruction: str
    arguments: Callable = _no_arguments
    # Nhãn router được ghi nhật ký cho lượt (knowledge_graph.intents.MODEL_INTENTS).
    intent: str = "READ"


_RECENT = ("hôm nay", "tuần này", "đêm qua", "tối qua", "gần đây")


def _health_arguments(match, _today):
    """Một tuần cho "hôm nay/tuần này/đêm qua", nếu không thì bốn tuần so với mốc."""
    return {
        "days": 7 if any(word in match.group(0) for word in _RECENT) else 28,
        "timezone": TIMEZONE,
    }


_LEAD = r"(?:xem |cho tôi xem |cho mình xem |kiểm tra |tra )?"
_OWNER = r"(?: của (?:tôi|mình|em))?"
FAST_TEMPLATES = (
    FastTemplate(
        TEMPLATE_ID,
        TEMPLATE_VERSION,
        "progress",
        "get_progress",
        re.compile(
            _LEAD
            + r"tiến độ (hôm nay|hôm qua|ngày \d{4}-\d{2}-\d{2}|từ \d{4}-\d{2}-\d{2} (?:đến|tới) \d{4}-\d{2}-\d{2})[.!?]?"
        ),
        "Trả lời yêu cầu tiến độ theo kết quả backend đã xác minh.",
        _progress_arguments,
    ),
    FastTemplate(
        "goals.current",
        1,
        "goals",
        "current_goal",
        re.compile(
            _LEAD
            + r"mục tiêu(?: hiện tại| đang thực hiện)?"
            + _OWNER
            + r"(?: là gì| thế nào)?[.!?]?"
        ),
        "Trả lời về mục tiêu hiện tại theo kết quả backend đã xác minh; không có bản ghi nghĩa là chưa đặt mục tiêu.",
    ),
    FastTemplate(
        "metrics.latest",
        1,
        "metrics",
        "latest_metrics",
        re.compile(
            _LEAD
            + r"(?:cân nặng|số đo|chỉ số cơ thể)(?: hiện tại| mới nhất| gần nhất| gần đây)?"
            + _OWNER
            + r"(?: là bao nhiêu| bao nhiêu)?[.!?]?"
        ),
        "Trả lời số đo mới nhất theo kết quả backend đã xác minh; không có bản ghi nghĩa là chưa ghi số đo.",
    ),
    FastTemplate(
        "profile.read",
        1,
        "profile",
        "get_profile",
        re.compile(_LEAD + r"hồ sơ(?: cá nhân)?" + _OWNER + r"[.!?]?"),
        "Tóm tắt hồ sơ theo kết quả backend đã xác minh.",
    ),
    FastTemplate(
        "nutrition.targets",
        1,
        "progress",
        "get_nutrition_targets",
        re.compile(
            r"(?:(?:mỗi ngày|một ngày|hôm nay) )?(?:(?:tôi|mình|em) )?(?:cần|nên|được|còn được|còn) (?:ăn )?(?:bao nhiêu|mấy) (?:calo|kcal)"
            r"(?: mỗi ngày| một ngày| hôm nay| nữa)?[.!?]?|"
            + _LEAD
            + r"mục tiêu (?:calo|kcal|dinh dưỡng|năng lượng)(?: hôm nay| mỗi ngày)?[.!?]?"
        ),
        "Trả lời mục tiêu năng lượng và macro, phần calo còn lại hôm nay theo kết quả backend đã xác minh; "
        "nêu ngắn gọn cách tính (BMR, TDEE) và cảnh báo nếu có. Thiếu dữ liệu hồ sơ thì nêu trường còn thiếu.",
        _timezone_argument,
    ),
)
_WHEN = r"(?:(?:hôm nay|tuần này|đêm qua|tối qua|gần đây) )?"
_WHO = r"(?:(?:tôi|mình|em) )?"
_TAIL = r"(?: hôm nay| tuần này| đêm qua| tối qua| gần đây)?(?: thế nào| ra sao| bao nhiêu)?[.!?]?"
_HEALTH = (
    "Trả lời theo phân tích dữ liệu thiết bị đã xác minh; nêu khoảng ngày và nguồn. Chưa kết nối, chưa cho phép "
    "hoặc chưa có dữ liệu thì hướng dẫn vào Cài đặt → Kết nối. Không chẩn đoán."
)
_DAY = r"(?: hôm nay| sáng nay)?"
# Độ sẵn sàng/hồi phục hôm nay: đánh giá tất định của backend (Daily Health Intelligence).
_READINESS = (
    "(?:"
    + r"(?:(?:hôm nay|sáng nay) )?"
    + _WHO
    + r"(?:có )?nên tập(?: nặng| cường độ cao| hết sức)?"
    + _DAY
    + r"(?: không| được không| hay nghỉ)"
    + "|"
    + _LEAD
    + r"(?:mức |độ )sẵn sàng(?: tập(?: luyện)?)?"
    + _OWNER
    + _DAY
    + r"(?: thế nào| ra sao)?"
    + "|"
    + _LEAD
    + r"(?:đánh giá )?(?:sức kh(?:oẻ|ỏe)|cơ thể)"
    + _OWNER
    + r" hôm nay(?: thế nào| ra sao)?"
    + "|"
    + r"(?:(?:hôm nay|sáng nay) )?"
    + _WHO
    + r"(?:hôm nay )?(?:đã )?hồi phục"
    + _DAY
    + r"(?: chưa| thế nào| ra sao)"
    + r")[.!?]?"
)
FAST_TEMPLATES += (
    FastTemplate(
        "health.readiness",
        1,
        "health",
        "get_health_assessment",
        re.compile(_READINESS),
        _HEALTH
        + " Nêu trạng thái sẵn sàng, độ tin cậy và 1–3 lý do chính kèm đúng con số so với nền của "
        "người dùng; thiếu dữ liệu thì nói rõ là chưa đủ để đánh giá.",
        _timezone_argument,
        "RECOVERY_REVIEW",
    ),
    FastTemplate(
        "health.activity",
        1,
        "health",
        "get_health_overview",
        re.compile(
            _LEAD
            + _WHEN
            + _WHO
            + r"(?:(?:đã )?đi (?:được )?(?:bao nhiêu|mấy) bước|(?:số bước|bước chân|mức vận động)"
            + _OWNER
            + ")"
            + _TAIL
        ),
        _HEALTH + " Tập trung vào bước chân, phút vận động so với WHO 150 phút/tuần.",
        _health_arguments,
        "ACTIVITY_REVIEW",
    ),
    FastTemplate(
        "health.sleep",
        1,
        "health",
        "get_health_overview",
        re.compile(
            _LEAD
            + _WHEN
            + _WHO
            + r"(?:ngủ (?:được )?(?:bao lâu|bao nhiêu tiếng|thế nào|ra sao)|giấc ngủ"
            + _OWNER
            + ")"
            + _TAIL
        ),
        _HEALTH
        + " Tập trung vào thời lượng ngủ so với khuyến nghị, giai đoạn ngủ và độ đều giờ ngủ.",
        _health_arguments,
        "SLEEP_REVIEW",
    ),
    FastTemplate(
        "health.recovery",
        1,
        "health",
        "get_health_overview",
        re.compile(_LEAD + _WHEN + r"(?:nhịp tim(?: nghỉ)?|hrv|mức phục hồi)" + _OWNER + _TAIL),
        _HEALTH + " Tập trung vào nhịp tim nghỉ và HRV so với nền 28 ngày.",
        _health_arguments,
        "RECOVERY_REVIEW",
    ),
)
TEMPLATES_BY_ID = {template.id: template for template in FAST_TEMPLATES}


def _normalized_request(state):
    return " ".join(latest_request(state).strip().casefold().split())


def make_fast_read_plan(state, now=None):
    """Ngữ pháp toàn tin nhắn cố ý từ chối yêu cầu ghép và ngầm định."""
    decision = state.get("decision", {})
    if (
        decision.get("action") != "tool"
        or decision.get("next_agent") != "tool"
        or decision.get("missing_fields")
        or state.get("pending_action")
        or state.get("candidate")
        or state.get("tool_outputs")
        or state.get("tool_count", 0)
        or state.get("status") in {"needs_input", "failed"}
        or not state.get("run_id")
    ):
        return None
    text = _normalized_request(state)
    today = (now or datetime.now(ZoneInfo(TIMEZONE))).astimezone(ZoneInfo(TIMEZONE)).date()
    for template in FAST_TEMPLATES:
        if template.domain != decision.get("domain"):
            continue
        match = template.pattern.fullmatch(text)
        if not match:
            continue
        try:
            args = REGISTRY[template.tool].normalize(template.arguments(match, today))
        except ValueError:
            return None
        return FastReadPlan(
            run_id=state["run_id"],
            template_id=template.id,
            template_version=template.version,
            registry_fingerprint=registry_fingerprint(),
            tool=template.tool,
            arguments=args,
        )
    return None


def fast_route(state, now=None):
    """Định tuyến do code quản lý cho lệnh đọc độc lập: trả về (decision, plan) hoặc None.

    Chỉ áp dụng cho bước định tuyến đầu tiên của một lượt chạy không có việc đang chờ, để
    câu hỏi nối tiếp, yêu cầu ghép hay workflow dở dang luôn đến được router LLM.
    """
    if (
        state.get("tool_outputs")
        or state.get("tool_count")
        or state.get("pending_action")
        or state.get("candidate")
        or state.get("catalog_handoff")
        or state.get("research_handoff")
        or state.get("research_count")
        or state.get("status") in {"needs_input", "failed"}
        or not state.get("run_id")
        or ((state.get("turn") or {}).get("run_id") == state.get("run_id"))
    ):
        return None
    text = _normalized_request(state)
    for template in FAST_TEMPLATES:
        if not template.pattern.fullmatch(text):
            continue
        from agentic.agents.state import RouteDecision

        decision = RouteDecision(
            intent=template.intent,
            action="tool",
            next_agent="tool",
            domain=template.domain,
            read_only=True,
            instruction=template.instruction,
        ).model_dump()
        plan = make_fast_read_plan({**state, "decision": decision}, now=now)
        return (decision, plan) if plan else None
    return None


def verified_fast_plan(state):
    try:
        plan = FastReadPlan.model_validate(state.get("fast_read_plan"))
        fresh = make_fast_read_plan(state)
        return plan if fresh and plan == fresh else None
    except ValueError:
        return None


def terminal_result(plan, output):
    """Một lần đọc nhanh có trả lời trọn mẫu của nó không (không cần định tuyến thêm)."""
    if plan.template_id == TEMPLATE_ID:
        return terminal_progress(plan, output)
    return True  # Lệnh đọc một bản ghi là trọn vẹn khi lời gọi thành công (404 = không có bản ghi).


def fast_answer_instruction(plan):
    template = TEMPLATES_BY_ID.get(plan.template_id)
    return template.instruction if template else "Trả lời theo kết quả backend đã xác minh."


def terminal_progress(plan, output):
    try:
        result = ProgressRead.model_validate(output)
    except (ValueError, TypeError):
        return False
    return (
        result.start_date.isoformat() == plan.arguments["start_date"]
        and result.end_date.isoformat() == plan.arguments["end_date"]
        and result.timezone == plan.arguments["timezone"]
        and len(result.days) == (result.end_date - result.start_date).days + 1
        and len({day.date for day in result.days}) == len(result.days)
        and all(result.start_date <= day.date <= result.end_date for day in result.days)
    )
