"""Phiên bản 4 của khung thẻ: thêm khung chọn ngày (mode date) cho hạn hoàn thành, ngày bắt đầu, ngày đã qua.

Trước đây câu hỏi ngày tháng chỉ có thể là mode text, nằm lại trong bong bóng chat và người dùng phải gõ tay (lượt
36cfc463: "Hạn hoàn thành: bạn muốn đặt hạn đến ngày nào?"). Model chỉ chọn mode date và hướng thời gian (when); khoảng
ngày và các mốc gợi ý do code dựng (services/clarification.date_frame).
"""

from agentic.prompts.v3.clarification import PROMPT as _V3

_ANCHOR = "- Số hiệp × reps × mức tạ của từng bài:"
if _V3.count(_ANCHOR) != 1:
    raise ValueError("Prompt base changed: clarification v3")

DATE_RULE = (
    "- Một ngày cụ thể (hạn hoàn thành, ngày bắt đầu, ngày mục tiêu, ngày đã diễn ra): mode date, options rỗng.\n"
    '  when = "future" cho hạn/ngày sắp tới, "past" cho ngày đã qua (ngày ghi, ngày đo), "any" khi cả hai đều hợp lý.\n'
    "  Không tự đặt khoảng ngày hay mốc gợi ý: HercFit tự dựng lịch và các mốc (4 tuần, 3 tháng...).\n"
)

PROMPT = _V3.replace(_ANCHOR, DATE_RULE + _ANCHOR).replace(
    "bằng cách bấm lựa chọn hoặc chọn số.", "bằng cách bấm lựa chọn, chọn số hoặc chọn ngày."
)
