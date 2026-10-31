"""Version 3: training logs go straight to the structured preview; quick gym logs by intensity."""

from agentic.prompts.v2.domains import COACH_GUIDANCE as _COACH_V2

# v2 let the tool model write a text "bản xem trước" and ask "xác nhận lưu?" when it had proposed a value
# itself (a start time the user skipped), which became a form of typed questions instead of the confirm card.
COACH_GUIDANCE = _COACH_V2.replace(
    '- Lịch tập dùng prescription',
    '''- Ghi nhanh buổi gym (người dùng chọn ghi theo cường độ): MỘT item của bài catalog gym_general "Tập gym (tổng
  quát)", performance SPORT {duration_seconds, intensity LIGHT/MODERATE/VIGOROUS}; không hỏi bài, hiệp, reps, mức tạ.
- Giờ bắt đầu không bắt buộc: dùng giờ hoặc buổi trong yêu cầu (sáng ~07:00, trưa ~12:00, chiều ~16:00, tối ~19:00),
  không có thì để mặc định; không hỏi riêng giờ. Nhiều hoạt động thiếu thông tin thì hỏi gộp một lần.
- Câu trả lời dạng "Nhãn: giá trị" là lựa chọn của người dùng từ form; "bỏ qua (bạn tự đề xuất)" nghĩa là dùng mặc
  định hợp lý, không hỏi lại. Hiệp "chưa ghi tạ" có weight_kg null (không phải 0); bài không dùng tạ ngoài (hít đất,
  xà đơn) dùng load_mode BODYWEIGHT. Đủ dữ liệu thì gọi create_trainings ngay: thẻ xác nhận chính là bản xem trước và người
  dùng sửa được ở đó; không viết bản xem trước bằng văn bản, không hỏi "xác nhận lưu?".
- Lịch tập dùng prescription''', 1)
