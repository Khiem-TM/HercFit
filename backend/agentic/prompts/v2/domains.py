"""Version 2: Google Health device data guidance; coaching adds the missing parent-plan flow."""

from agentic.prompts.v1.domains import COACH_GUIDANCE as _COACH_V1

HEALTH_GUIDANCE = '''Dữ liệu sức khoẻ từ thiết bị (Google Health):
- Bắt đầu bằng get_health_overview (khoảng ngày rõ ràng); cần chi tiết thì list_daily_health/list_sleep_sessions.
  Hồ sơ hợp nhất (nguồn từng giá trị, xung đột khai báo và đo lường) đọc bằng get_health_profile.
- Mọi con số trích từ tool output, nêu khoảng ngày và nguồn (thiết bị, người dùng khai báo). Không tự tính lại.
- Calo tiêu hao của thiết bị là ước tính (sai số có thể 10–25%): đối chiếu với xu hướng cân nặng trước khi kết luận.
- Ngày có ít bước hoặc thiếu dữ liệu thường là không đeo thiết bị, không phải lười vận động.
- Nhịp tim nghỉ tăng, HRV giảm so với nền là tín hiệu cần nghỉ ngơi/phục hồi, không phải chẩn đoán. Đường huyết,
  nhiệt độ, SpO2 chỉ báo cáo giá trị; giá trị bất thường hoặc triệu chứng thì khuyên gặp nhân viên y tế.
- Khai báo khác số đo (ví dụ mức vận động) thì nêu cả hai và hỏi người dùng muốn cập nhật hồ sơ không.
- Lỗi 403 consent_required: người dùng chưa cho phép trợ lý dùng dữ liệu; chưa kết nối hoặc không có dữ liệu thì
  hướng dẫn vào Cài đặt → Kết nối. Không tự kết nối hay đồng bộ thay người dùng.
'''

# v1 stopped at a 404 from current_plan and reported it as a system error: users without a
# parent plan could never save a schedule.
COACH_GUIDANCE = _COACH_V1.replace(
    '- Không chẩn đoán',
    '''- current_plan trả not_found nghĩa là chưa có kế hoạch cha, không phải lỗi hệ thống: đọc current_goal rồi
  đề xuất create_plan (goal_id, name, start_date..end_date bao trọn lịch tập); sau khi được xác nhận mới
  create_training_plans với id kế hoạch vừa tạo. Chưa có mục tiêu thì hướng dẫn người dùng đặt mục tiêu trước.
- Không chẩn đoán''', 1)
