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

# Đặt/sửa/kết thúc mục tiêu là lệnh ghi có xác nhận: router v6 không có nhãn cho chúng nên model tự đặt (SET_GOAL,
# GOAL_UPDATE) và luật tư vấn coi chúng là câu hỏi cần tra cứu (lượt 36cfc463).
GOAL_RULES = (
    "Mục tiêu: đặt mục tiêu mới là intent GOAL_SET; sửa, kết thúc sớm, hoàn thành hay huỷ mục tiêu đang theo là\n"
    "GOAL_UPDATE (yêu cầu gồm cả hai việc dùng GOAL_UPDATE). Đây là lệnh ghi domain goals, không phải câu hỏi tư vấn,\n"
    "không research. Đủ thông tin thì action tool. Thiếu thì action clarify và liệt kê missing_fields, mỗi thông tin một\n"
    "mục ngắn (vd. loại mục tiêu, hạn hoàn thành, cân nặng mục tiêu); HercFit hỏi chúng bằng thẻ, không hỏi bằng văn bản.\n"
)

ROUTING_PROMPT = _revise(_V6_ROUTING, CONTEXT_RULES) + GOAL_RULES
NORMAL_ROUTING_PROMPT = _revise(_V6_NORMAL, CONTEXT_RULES) + GOAL_RULES

# Chế độ ghi nhanh không có miền goals: lời mời nói đúng việc người dùng muốn làm thay vì gọi nó là tư vấn.
PLAN_MODE_WRITE_REPLY = (
    "Đặt hoặc thay đổi mục tiêu được thực hiện ở chế độ Plan, nơi HercFit đọc mục tiêu hiện tại của bạn và hỏi các "
    'thông tin còn thiếu bằng thẻ. Bấm "Hỏi ở chế độ Plan" bên dưới để gửi lại yêu cầu này.'
)
