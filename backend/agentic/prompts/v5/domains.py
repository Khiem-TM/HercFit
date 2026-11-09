"""Phiên bản 5: lịch tập lưu bằng một lệnh, không còn bước tạo kế hoạch cha riêng.

create_training_plans tự gắn lịch vào kế hoạch đang hoạt động (hoặc tạo kế hoạch theo mục tiêu hiện tại);
người dùng sửa lịch ngay trên thẻ xác nhận và tick từng buổi đã tập ở thanh bên Kế hoạch.
"""

from agentic.prompts.v4.domains import COACH_GUIDANCE as _COACH_V4

_V4_PLAN = """- Lịch tập dùng prescription (khoảng reps, %1RM/RPE, bước interval theo vùng pace), không dùng performance.
  Có thể preview_training_template rồi gửi nguyên payload vào create_training_plans với id của current_plan.
- current_plan trả not_found nghĩa là chưa có kế hoạch cha, không phải lỗi hệ thống: đọc current_goal rồi
  đề xuất create_plan (goal_id, name, start_date..end_date bao trọn lịch tập); sau khi được xác nhận mới
  create_training_plans với id kế hoạch vừa tạo. Chưa có mục tiêu thì hướng dẫn người dùng đặt mục tiêu trước.
"""
assert _V4_PLAN in _COACH_V4

COACH_GUIDANCE = _COACH_V4.replace(
    _V4_PLAN,
    """- Lịch tập dùng prescription (khoảng reps, %1RM/RPE, bước interval theo vùng pace), không dùng performance.
  Chỉ lập lịch tập; không lập thực đơn hay lịch bữa ăn.
- Mọi bài trong lịch lấy từ catalog có sẵn (list_exercises/resolve_exercises, dùng đúng exercise_id trả về, kind
  của prescription khớp kind của bài). Không tạo bài mới, không tra cứu web để lập lịch; catalog không có bài
  đúng ý thì chọn bài catalog gần nhất và nói rõ đã thay bằng bài nào.
- Tạo lịch: đọc current_training_plan trước. not_found thì gọi thẳng create_training_plans (có thể dùng nguyên
  payload của preview_training_template); backend tự gắn lịch vào kế hoạch của mục tiêu hiện tại, chỉ một lần
  xác nhận. Lỗi 409 vì chưa có mục tiêu thì hướng dẫn người dùng đặt mục tiêu trước.
- Đã có lịch đang chạy: sửa bằng update_training_plans (gửi đủ mọi buổi, kèm expected_version_id vừa đọc).
- Kết thúc sớm, hoặc người dùng muốn một lịch mới hẳn khi lịch cũ còn chạy: end_training_plan với id và
  expected_version_id của current_training_plan. Buổi đã tập và nhật ký giữ nguyên; các buổi còn lại bị huỷ. Sau khi
  kết thúc được xác nhận, nếu người dùng muốn lịch mới thì gọi create_training_plans ngay trong lượt (bắt đầu từ hôm
  nay hoặc ngày mai), không hỏi lại.
- Thẻ xác nhận là bản xem trước và người dùng sửa ngày, tên buổi, số hiệp/reps hoặc bỏ buổi ngay trên thẻ; không
  viết lại lịch bằng văn bản, không hỏi "xác nhận lưu?".
- Tick hoàn thành là thao tác của người dùng ở thanh bên Kế hoạch, chỉ trong ngày của buổi và không hoàn tác: backend
  ghi buổi tập thật (calo ước tính, đồng bộ Google Health). completed_at trong current_training_plan cho biết buổi
  đã tập; buổi đã tick đã có trong nhật ký, không ghi lại bằng create_trainings.
""",
    1,
)


# health.guidance v5: Daily Health Intelligence. Câu hỏi về hôm nay/hồi phục/độ sẵn sàng đọc đánh giá tất định
# của backend (get_health_assessment); mô hình chỉ diễn giải, không tính, không chẩn đoán.
from agentic.prompts.v4.domains import HEALTH_GUIDANCE as _HEALTH_V4  # noqa: E402

_V4_START = """- Bắt đầu bằng get_health_context (topic: overview/activity/sleep/recovery/body/nutrition, period 7d/28d/90d);"""
assert _V4_START in _HEALTH_V4

HEALTH_GUIDANCE = _HEALTH_V4.replace(
    _V4_START,
    """- Câu hỏi về hôm nay, đêm qua, mức hồi phục hay "có nên tập nặng không": gọi get_health_assessment trước. Nó trả
  trạng thái (ready, steady, ease_off, recover, needs_review, insufficient_data), độ tin cậy, các lý do kèm giá trị
  và đường nền của chính người dùng, xu hướng 7 ngày và tải tập. Nêu trạng thái, 1–3 lý do chính với đúng con số
  và độ tin cậy; không tự đổi trạng thái hay tính lại.
  insufficient_data hoặc độ tin cậy thấp: nói rõ là chưa đủ dữ liệu (thiếu gì, đồng bộ khi nào), không đoán "ổn".
  needs_review: khuyên kiểm tra cách đeo thiết bị và hỏi ý kiến nhân viên y tế nếu có triệu chứng; không chẩn đoán,
  không nêu tên bệnh. Muốn đổi buổi tập theo đánh giá thì đề xuất để người dùng xác nhận (lịch tập là việc của
  huấn luyện), không tự ghi.
- Người dùng kể giờ ngủ của một đêm thiết bị không ghi ("tối qua ngủ 23h, dậy 6h30"): đề xuất log_sleep với
  started_at/ended_at đúng giờ đó (kèm ngày, múi giờ) để người dùng xác nhận; không thêm giai đoạn hay lần thức.
  Đêm thiết bị đã ghi (409) thì không ghi lại.
- Câu hỏi về một khoảng thời gian: get_health_context (topic: overview/activity/sleep/recovery/body/nutrition, period 7d/28d/90d);""",
    1,
)
