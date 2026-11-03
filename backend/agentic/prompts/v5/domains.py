"""Phiên bản 5: lịch tập lưu bằng một lệnh, không còn bước tạo kế hoạch cha riêng.

create_training_plans tự gắn lịch vào kế hoạch đang hoạt động (hoặc tạo kế hoạch theo mục tiêu hiện tại);
người dùng sửa lịch ngay trên thẻ xác nhận và tick từng buổi đã tập ở thanh bên Kế hoạch.
"""

from agentic.prompts.v4.domains import COACH_GUIDANCE as _COACH_V4

_V4_PLAN = '''- Lịch tập dùng prescription (khoảng reps, %1RM/RPE, bước interval theo vùng pace), không dùng performance.
  Có thể preview_training_template rồi gửi nguyên payload vào create_training_plans với id của current_plan.
- current_plan trả not_found nghĩa là chưa có kế hoạch cha, không phải lỗi hệ thống: đọc current_goal rồi
  đề xuất create_plan (goal_id, name, start_date..end_date bao trọn lịch tập); sau khi được xác nhận mới
  create_training_plans với id kế hoạch vừa tạo. Chưa có mục tiêu thì hướng dẫn người dùng đặt mục tiêu trước.
'''
assert _V4_PLAN in _COACH_V4

COACH_GUIDANCE = _COACH_V4.replace(_V4_PLAN, '''- Lịch tập dùng prescription (khoảng reps, %1RM/RPE, bước interval theo vùng pace), không dùng performance.
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
''', 1)
