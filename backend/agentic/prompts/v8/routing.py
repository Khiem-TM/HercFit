"""Phiên bản 8: câu hỏi xem/phân tích dữ liệu đã lưu đi qua context graph, không còn bắt buộc đọc backend.

Router đặt action answer cùng context (focus, entities, start/end); HercFit truy vấn context graph rồi trả lời, và tự
chuyển sang đọc backend khi graph thiếu hoặc chưa đồng bộ (agents/workflow.py). Phần còn lại giữ nguyên v6.
"""

from agentic.prompts.v6.routing import NORMAL_ROUTING_PROMPT as _V6_NORMAL
from agentic.prompts.v6.routing import ROUTING_PROMPT as _V6_ROUTING
from agentic.prompts.v6.routing import _revise

CONTEXT_RULES = (
    (
        "Cân nặng, buổi tập, số đo đã có trong backend: đọc bằng tool trước, không hỏi lại người dùng.\n",
        "Cân nặng, bữa ăn, buổi tập, số đo, giấc ngủ, mục tiêu đã lưu: không hỏi lại người dùng.\n",
    ),
    (
        "Dữ liệu cá nhân/hệ thống phải đọc backend; thiếu thông tin bắt buộc phải clarify.\n",
        "Xem hoặc phân tích dữ liệu đã lưu (bữa ăn, dinh dưỡng theo ngày/tuần/tháng, buổi tập, bài tập, cân nặng, giấc\n"
        "ngủ, vận động, mục tiêu, các lượt trước của cuộc trò chuyện): action answer, domain đúng nhóm, và điền context\n"
        "(focus; entities là tên món/bài tập được nhắc; start/end chỉ khi người dùng nêu ngày cụ thể). HercFit tự truy vấn\n"
        "context graph trước khi trả lời và tự đọc backend khi graph thiếu; không gọi tool chỉ để đọc dữ liệu đã lưu.\n"
        "focus: summary (tổng hợp), list (liệt kê bản ghi), top (nhiều nhất), trend (xu hướng, so sánh theo thời gian),\n"
        "latest (lần gần nhất, hiện tại), relation (liên hệ giữa các miền, vd. ngủ và tập), followup (về lượt trước).\n"
        'Số do backend tính (mục tiêu calo/macro, BMR/TDEE, "còn được ăn bao nhiêu", đánh giá sức khoẻ/độ sẵn sàng,\n'
        "insights/PR/tải tập) vẫn là action tool. Ghi/sửa/xoá luôn là action tool; điền thêm context khi cần dữ liệu cũ\n"
        '(vd. "ăn như hôm qua"). Thiếu thông tin bắt buộc để ghi thì clarify.\n',
    ),
)

ROUTING_PROMPT = _revise(_V6_ROUTING, CONTEXT_RULES)
NORMAL_ROUTING_PROMPT = _revise(_V6_NORMAL, CONTEXT_RULES)
