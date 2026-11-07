"""Định tuyến đọc JEV thận trọng; mọi lệnh ghi giữ nguyên luồng điều phối hiện có."""

import math
import re

from agentic.prompts.registry import get_questions
from agentic.prompts.v2.routing import JEV_READ_ROUTES
from agentic.services.routing import latest_request
from domains.catalog.models.foods import normalize_food_text

JEV_ROUTING_QUESTIONS = get_questions("routing.jev", "v2")


def jev_routing_projection(state):
    """Giữ cổng lọc ứng viên rẻ; lịch sử và ảnh chụp dữ liệu cá nhân không bao giờ ra khỏi nó."""
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
        return None
    text = latest_request(state).strip()
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
    return {"request": text, "task": "standalone_read", "has_pending_action": False}


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
