"""Tra cứu prompt tường minh, có phiên bản, không có mạng, biến môi trường hay trạng thái runtime.

Giữ phiên bản 1 ổn định. Hướng dẫn thay đổi thì có phiên bản và đánh giá mới;
bên gọi chủ động chọn dùng thay vì âm thầm đổi hành vi của agent đang chạy.
"""

from copy import deepcopy
from types import MappingProxyType

from agentic.prompts.v1.answer import ANSWER_PROMPT
from agentic.prompts.v1.clarification import PROMPT as CLARIFICATION_PROMPT
from agentic.prompts.v1.domains import CAPABILITY_GUIDANCE, COACH_GUIDANCE
from agentic.prompts.v1.jev import RESEARCH_QUESTIONS
from agentic.prompts.v1.memory import SUMMARY_PROMPT
from agentic.prompts.v1.research import PROMPT as RESEARCH_PROMPT
from agentic.prompts.v1.routing import GRAPH_CONTEXT_GUIDANCE, JEV_ROUTING_QUESTIONS, ROUTING_PROMPT
from agentic.prompts.v1.tool import PROMPT as TOOL_PROMPT
from agentic.prompts.v2 import routing as v2_routing
from agentic.prompts.v2.clarification import PROMPT as CLARIFICATION_PROMPT_V2
from agentic.prompts.v2.domains import COACH_GUIDANCE as COACH_GUIDANCE_V2
from agentic.prompts.v2.domains import HEALTH_GUIDANCE
from agentic.prompts.v2.personal import PERSONAL_ROUTING, PERSONALIZED_ANSWER
from agentic.prompts.v3 import routing as v3_routing
from agentic.prompts.v3.clarification import PROMPT as CLARIFICATION_PROMPT_V3
from agentic.prompts.v3.domains import COACH_GUIDANCE as COACH_GUIDANCE_V3
from agentic.prompts.v3.domains import HEALTH_GUIDANCE as HEALTH_GUIDANCE_V3
from agentic.prompts.v4.domains import COACH_GUIDANCE as COACH_GUIDANCE_V4
from agentic.prompts.v4.domains import HEALTH_GUIDANCE as HEALTH_GUIDANCE_V4
from agentic.prompts.v5.domains import COACH_GUIDANCE as COACH_GUIDANCE_V5

TEMPLATES = MappingProxyType(
    {
        ("orchestration.route", "v1"): ROUTING_PROMPT,
        ("orchestration.answer", "v1"): ANSWER_PROMPT,
        ("orchestration.graph_context", "v1"): GRAPH_CONTEXT_GUIDANCE,
        ("tool.call", "v1"): TOOL_PROMPT,
        ("research.extract", "v1"): RESEARCH_PROMPT,
        ("clarification.form", "v1"): CLARIFICATION_PROMPT,
        ("memory.summary", "v1"): SUMMARY_PROMPT,
        ("nutrition.capabilities", "v1"): CAPABILITY_GUIDANCE,
        ("training.coach", "v1"): COACH_GUIDANCE,
        # v2: dữ liệu thiết bị Google Health và ý định cơ thể/hồ sơ chi tiết hơn.
        ("orchestration.route", "v2"): v2_routing.ROUTING_PROMPT,
        ("health.guidance", "v2"): HEALTH_GUIDANCE,
        ("training.coach", "v2"): COACH_GUIDANCE_V2,
        # v2: tư vấn cá nhân hoá từ dữ liệu đã lưu của người dùng cộng tri thức đã kiểm chứng.
        ("orchestration.personal", "v2"): PERSONAL_ROUTING,
        ("orchestration.personal_answer", "v2"): PERSONALIZED_ANSWER,
        # v2: lựa chọn catalog có thể chọn nhiều và không bao giờ đến người dùng mà thiếu các phương án.
        ("clarification.form", "v2"): CLARIFICATION_PROMPT_V2,
        # v3: nhật ký tập đi thẳng tới bản xem trước có cấu trúc; ghi nhanh buổi gym theo cường độ.
        ("training.coach", "v3"): COACH_GUIDANCE_V3,
        # v3: ưu tiên context API có nguồn; thiếu độ phủ là chưa biết, không bao giờ là "không đeo".
        ("health.guidance", "v3"): HEALTH_GUIDANCE_V3,
        # v3: chỉ dùng khung trên thẻ (lựa chọn, số kèm đơn vị, chọn catalog); không có câu trả lời văn bản tự do.
        ("clarification.form", "v3"): CLARIFICATION_PROMPT_V3,
        # v4: Google Health là nguồn sự thật cho thể thao/số đo/nước; nhật ký tập chỉ còn gym.
        ("training.coach", "v4"): COACH_GUIDANCE_V4,
        ("health.guidance", "v4"): HEALTH_GUIDANCE_V4,
        # v5: lịch tập lưu bằng một lệnh, sửa trên thẻ xác nhận; không còn lịch bữa ăn.
        ("training.coach", "v5"): COACH_GUIDANCE_V5,
        # v3: định tuyến theo chế độ trò chuyện: bản rút gọn cho ghi nhanh, khối hướng dẫn cho chế độ Plan.
        ("orchestration.route_normal", "v3"): v3_routing.NORMAL_ROUTING_PROMPT,
        ("orchestration.plan", "v3"): v3_routing.PLAN_ROUTING,
        ("orchestration.plan_mode_reply", "v3"): v3_routing.PLAN_MODE_REPLY,
    }
)

_QUESTIONS = {
    ("routing.jev", "v1"): JEV_ROUTING_QUESTIONS,
    ("routing.jev", "v2"): v2_routing.JEV_ROUTING_QUESTIONS,
    **{("research." + phase, "v1"): questions for phase, questions in RESEARCH_QUESTIONS.items()},
}


def get_prompt(name: str, version: str = "v1") -> str:
    """Trả về đúng mẫu; chỉ điền các trường động tại nơi gọi."""
    return TEMPLATES[(name, version)]


def get_questions(name: str, version: str = "v1") -> dict:
    """Trả về một bản sao tách biệt để bộ đánh giá không sửa được chính sách của lượt chạy khác."""
    return deepcopy(_QUESTIONS[(name, version)])
