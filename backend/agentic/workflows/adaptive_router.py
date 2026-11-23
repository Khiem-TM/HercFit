"""Định tuyến đọc JEV thận trọng; mọi lệnh ghi giữ nguyên luồng điều phối hiện có."""

import math
import re

from agentic.prompts.registry import get_questions
from agentic.prompts.v2 import JEV_READ_ROUTES
from agentic.workflows.routing import TEMPLATE_ID, jev_fast_read_plan, latest_request
from domains.catalog.models import normalize_food_text

JEV_ROUTING_QUESTIONS = get_questions("routing.jev", "v2")
VERIFY_READ_QUESTIONS = get_questions("routing.verify_read")
_VERIFY_EXCLUDED = re.compile(
    r"\b(?:(?<!nap )(?<!an )them|tao|(?<!da )luu|xoa|sua|cap nhat|doi|ghi nhan|xac nhan|"
    r"add|create|save|delete|remove|update|change|replace|cancel|confirm|"
    r"va|dong thoi|sau do|roi|kem|tien de|tiep theo|and|also|then|"
    r"cai do|nhu tren|nhu cu|cach tinh tren|tiep tuc|noi lai|that one|same|again|continue|"
    r"web|internet|nghien cuu|research|online|bo qua|ignore|system prompt)\b"
)
_METRIC_DESCRIPTIONS = {"weight_kg": "cân nặng", "height_cm": "chiều cao", "body_fat_pct": "tỷ lệ mỡ cơ thể"}


def _routing_request(state):
    decision = state.get("decision") or {}
    if (
        state.get("tool_outputs")
        or state.get("tool_count")
        or state.get("pending_action")
        or state.get("candidate")
        or state.get("catalog_handoff")
        or state.get("research_handoff")
        or state.get("research_count")
        or state.get("research_work")
        or state.get("research_answer")
        or decision.get("objectives")
        or decision.get("read_only")
        or ((state.get("turn") or {}).get("run_id") == state.get("run_id") and state.get("turn"))
    ):
        return ""
    return latest_request(state).strip()


def jev_routing_projection(state):
    """Giữ cổng lọc ứng viên rẻ; lịch sử và ảnh chụp dữ liệu cá nhân không bao giờ ra khỏi nó."""
    text = _routing_request(state)
    normalized = normalize_food_text(text)
    # Lệnh ghi rõ ràng, yêu cầu ghép, câu hỏi nối tiếp dùng đại từ và yêu cầu tra cứu tường minh
    # đi theo đường cơ sở, không tốn thêm một lần gọi phân loại.
    if not text or re.search(
        r"\b(?:ghi|them|tao|luu|xoa|sua|cap nhat|dang ky|dat lich|len lich|len ke hoach|thiet ke|"
        r"add|create|save|delete|remove|update|record|change|replace|cancel|complete|"
        r"va|dong thoi|sau do|roi|kem|and|also|then|"
        r"mon do|bai do|cai do|nhu tren|nhu cu|vua roi|tiep tuc|no|again|it|that|those|same|continue|"
        r"web|internet|nghien cuu|nguon ben ngoai|research|online)\b",
        normalized,
    ):
        return None
    return {"request": _redacted_request(text), "task": "standalone_read", "has_pending_action": False}


def _redacted_request(text):
    # Phòng thủ nhiều lớp trước bước che thông tin theo danh tính của service. Không đưa
    # ID người dùng/phiên/lượt chạy, trường hồ sơ, thông tin xác thực backend hay lịch sử vào đây.
    text = re.sub(r"(?i)\bBearer\s+\S+", "[credential]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "[identifier]",
        text,
    )
    text = re.sub(r"(?<!\w)(?:\+?\d[\s().-]*){10,15}(?!\w)", "[phone]", text)
    return text


def proposed_read(state):
    text = _routing_request(state)
    if (
        not text
        or len(text) > 500
        or "\n" in text
        or text.count("?") > 1
        or state.get("food_choices")
        or state.get("food_gap")
        or state.get("catalog_choice")
        or state.get("replying_to_form")
        or _VERIFY_EXCLUDED.search(normalize_food_text(text))
    ):
        return None
    plan = jev_fast_read_plan(state)
    if plan is None:
        return None
    if plan.template_id == TEMPLATE_ID:
        start, end = (plan.arguments[key] for key in ("start_date", "end_date"))
        # Những biểu thức tương đối đã được code đổi sang khoảng ngày của cùng thao tác.
        normalized = normalize_food_text(text)
        if re.search(r"\b(?:hom nay|today)\b", normalized):
            period = "hôm nay"
        elif re.search(r"\b(?:hom qua|yesterday)\b", normalized):
            period = "hôm qua"
        else:
            period = f"ngày {start}" if start == end else f"từ {start} đến {end}"
        description = f"Xem tổng kcal và macro từ nhật ký ăn uống {period} của tôi."
    elif plan.template_id == "metrics.latest":
        metric = _METRIC_DESCRIPTIONS[plan.arguments.get("field", "weight_kg")]
        description = f"Đọc {metric} mới nhất đã lưu của tôi."
    else:
        description = "Xem mức dinh dưỡng mục tiêu mỗi ngày hoặc lượng còn lại hôm nay."
    return plan, {"request": _redacted_request(text), "proposed_read": description}


def accepts_proposed_read(evaluation, threshold):
    probability = ((evaluation.get("answers") or {}).get("equivalent") or {}).get("noul")
    return (
        evaluation.get("status") == "ok"
        and not evaluation.get("reason")
        and type(probability) in (float, int)
        and threshold <= probability <= 1
    )


def verify_read_event(state):
    return next(
        (
            event for event in reversed(state.get("jev_events") or [])
            if event.get("gate") == "routing" and event.get("template")
        ),
        None,
    )


def jev_read_domain(evaluation):
    if evaluation.get("status") != "ok":
        return None
    answers = evaluation.get("answers") or {}
    route = answers.get("route") or {}
    confidence = route.get("confidence")
    if (
        route.get("choice") not in JEV_READ_ROUTES
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
        or not 0.9 <= confidence <= 1
    ):
        return None
    for name in ("mutation", "multiple", "dependency", "web"):
        probability = (answers.get(name) or {}).get("noul")
        if (
            not isinstance(probability, (int, float))
            or isinstance(probability, bool)
            or not math.isfinite(probability)
            or not 0 <= probability <= 0.1
        ):
            return None
    return route["choice"]
