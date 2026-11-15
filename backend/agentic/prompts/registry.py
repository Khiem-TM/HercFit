"""Tra cứu prompt tường minh, có phiên bản, không có mạng, biến môi trường hay trạng thái runtime.

Hướng dẫn thay đổi thì có phiên bản và đánh giá mới; bên gọi chủ động chọn dùng thay vì âm thầm đổi hành vi của agent
đang chạy. Mỗi khoá chỉ đăng ký phiên bản đang được gọi và một phiên bản liền trước (để so sánh khi đánh giá); module
của các phiên bản cũ hơn vẫn ở lại vì phiên bản mới được dựng nối tiếp từ chúng.
"""

from copy import deepcopy
from types import MappingProxyType

from agentic.prompts.v1.answer import ANSWER_PROMPT
from agentic.prompts.v1.jev import RESEARCH_QUESTIONS
from agentic.prompts.v1.memory import SUMMARY_PROMPT
from agentic.prompts.v1.notifications import ALERT_PROMPT, REVIEW_PROMPT
from agentic.prompts.v1.nutrition import NUTRITION_LOOKUP_PROMPT
from agentic.prompts.v1.research import PROMPT as RESEARCH_PROMPT
from agentic.prompts.v1.routing import GRAPH_CONTEXT_GUIDANCE, JEV_ROUTING_QUESTIONS
from agentic.prompts.v1.tool import PROMPT as TOOL_PROMPT
from agentic.prompts.v2 import routing as v2_routing
from agentic.prompts.v2.personal import PERSONAL_ROUTING, PERSONALIZED_ANSWER
from agentic.prompts.v3 import routing as v3_routing
from agentic.prompts.v3.clarification import PROMPT as CLARIFICATION_PROMPT_V3
from agentic.prompts.v5.domains import COACH_GUIDANCE as COACH_GUIDANCE_V5
from agentic.prompts.v5.domains import HEALTH_GUIDANCE as HEALTH_GUIDANCE_V5
from agentic.prompts.v6 import routing as v6_routing
from agentic.prompts.v6.domains import CAPABILITY_GUIDANCE as CAPABILITY_GUIDANCE_V6
from agentic.prompts.v7.domains import CAPABILITY_GUIDANCE as CAPABILITY_GUIDANCE_V7
from agentic.prompts.v7.tool import PROMPT as TOOL_PROMPT_V7
from agentic.prompts.v8 import clarification as v8_clarification
from agentic.prompts.v8 import context as v8_context
from agentic.prompts.v8 import domains as v8_domains
from agentic.prompts.v8 import nutrition as v8_nutrition
from agentic.prompts.v8 import routing as v8_routing

TEMPLATES = MappingProxyType(
    {
        ("orchestration.answer", "v1"): ANSWER_PROMPT,
        ("orchestration.graph_context", "v1"): GRAPH_CONTEXT_GUIDANCE,
        ("tool.call", "v1"): TOOL_PROMPT,
        ("research.extract", "v1"): RESEARCH_PROMPT,
        ("memory.summary", "v1"): SUMMARY_PROMPT,
        # v2: tư vấn cá nhân hoá từ dữ liệu đã lưu của người dùng cộng tri thức đã kiểm chứng.
        ("orchestration.personal", "v2"): PERSONAL_ROUTING,
        ("orchestration.personal_answer", "v2"): PERSONALIZED_ANSWER,
        # v3: chỉ dùng khung trên thẻ (lựa chọn, số kèm đơn vị, chọn catalog); không có câu trả lời văn bản tự do.
        ("clarification.form", "v3"): CLARIFICATION_PROMPT_V3,
        # v5: lịch tập lưu bằng một lệnh, sửa trên thẻ xác nhận; không còn lịch bữa ăn.
        ("training.coach", "v5"): COACH_GUIDANCE_V5,
        # v5: Daily Health Intelligence: hôm nay/hồi phục/độ sẵn sàng đọc đánh giá tất định get_health_assessment.
        ("health.guidance", "v5"): HEALTH_GUIDANCE_V5,
        # v3: khối hướng dẫn cho chế độ Plan.
        ("orchestration.plan", "v3"): v3_routing.PLAN_ROUTING,
        ("orchestration.plan_mode_reply", "v3"): v3_routing.PLAN_MODE_REPLY,
        # v1: thông báo chủ động (cảnh báo chỉ số, đánh giá ngày) viết từ feature và nhãn tất định của backend.
        ("notifications.alert", "v1"): ALERT_PROMPT,
        ("notifications.review", "v1"): REVIEW_PROMPT,
        # v6: món ăn không tra cứu web; catalog chưa có món thì hỏi bằng thẻ tìm món/tạo món riêng.
        ("orchestration.route", "v6"): v6_routing.ROUTING_PROMPT,
        ("orchestration.route_normal", "v6"): v6_routing.NORMAL_ROUTING_PROMPT,
        ("nutrition.capabilities", "v6"): CAPABILITY_GUIDANCE_V6,
        # v1: gợi ý 4 chỉ số dinh dưỡng (trên 100 g) cho món riêng tạo trên thẻ món thiếu, chép nguyên văn từ một nguồn.
        ("nutrition.lookup", "v1"): NUTRITION_LOOKUP_PROMPT,
        # v7: mọi món tính theo 100 g/100 ml; tô/suất quy ra gam/ml bằng portions, không còn PORTION.
        ("nutrition.capabilities", "v7"): CAPABILITY_GUIDANCE_V7,
        ("tool.call", "v7"): TOOL_PROMPT_V7,
        # v8: Context Graph (text-to-Cypher). Câu hỏi đọc dữ liệu đã lưu đi qua context graph, không bắt buộc đọc
        # backend; Context Agent viết Cypher theo lược đồ knowledge_graph.schema.
        ("orchestration.route", "v8"): v8_routing.ROUTING_PROMPT,
        ("orchestration.route_normal", "v8"): v8_routing.NORMAL_ROUTING_PROMPT,
        ("orchestration.graph_context", "v2"): v8_context.GRAPH_CONTEXT_GUIDANCE,
        ("orchestration.graph_answer", "v1"): v8_context.ANSWER_GRAPH_GUIDANCE,
        ("context.cypher", "v1"): v8_context.CYPHER_PROMPT,
        # v8: lệnh ghi mục tiêu (GOAL_SET/GOAL_UPDATE) hỏi lại bằng thẻ; lời mời sang Plan cho lệnh ghi; khung ngày.
        ("orchestration.plan_mode_write_reply", "v1"): v8_routing.PLAN_MODE_WRITE_REPLY,
        ("clarification.form", "v4"): v8_clarification.PROMPT,
        # v8: gợi ý dinh dưỡng chép số từ nguồn khi có, nếu không thì ước tính trên 100 g (được đánh dấu là ước tính).
        ("nutrition.lookup", "v2"): v8_nutrition.LOOKUP_PROMPT,
        # v8: buổi thể thao, nước, giấc ngủ, số đo lưu trong HercFit trước; Google chỉ là đích đồng bộ khi đã kết nối.
        ("training.coach", "v6"): v8_domains.COACH_GUIDANCE,
        ("health.guidance", "v6"): v8_domains.HEALTH_GUIDANCE,
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
