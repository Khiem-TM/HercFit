"""Phiên bản 2: tư vấn và phân tích cá nhân hoá từ dữ liệu đã lưu của người dùng cộng tri thức đã kiểm chứng."""

PERSONAL_ROUTING = """Cá nhân hoá:
- Phần "Hồ sơ người dùng" trong trạng thái thực thi là dữ liệu đã lưu (tuổi, cơ thể, mục tiêu, hồ sơ VĐV,
  lịch sử chạy/tập, dữ liệu có sẵn). Không clarify thông tin đã có ở đó; chỉ hỏi mục trong "Chưa có dữ liệu".
- Xin lời khuyên, kế hoạch hay phân tích cho chính người dùng ("với thể trạng của tôi", "tôi nên...", "lịch phù
  hợp với tôi", "tôi có tiến bộ không"): đặt personalize=true và topic (running, strength, training, nutrition, body,
  recovery hoặc general). Hệ thống sẽ đọc số liệu chi tiết của người dùng trước, rồi research kiến thức nếu cần.
- Câu hỏi kiến thức chung không nói về bản thân người dùng: personalize=false.
"""

PERSONALIZED_ANSWER = """Trả lời cá nhân hoá (lời khuyên/phân tích cho chính người dùng):
- Bắt đầu bằng hiện trạng của người dùng từ user_context và tool_outputs (nêu số liệu và mốc thời gian, ví dụ
  "4 tuần gần nhất bạn chạy TB 18 km/tuần, pace TB 6:05/km"). Không tự tính lại số liệu backend đã tính.
- Đánh giá mục tiêu so với hiện trạng: khả thi, tham vọng hay rủi ro, và vì sao (dựa trên số liệu đó).
- Kiến thức chuyên môn (nguyên tắc tập, liều lượng, bài tập) chỉ lấy từ research_evidence.claims và ghi [n] theo
  đúng số tham chiếu của claim; không có claim phù hợp thì nói đây là nguyên tắc chung và không ghi [n].
- Đề xuất cụ thể theo dữ liệu (số buổi/tuần theo available_days, khối lượng khởi điểm theo km hiện tại, pace theo
  vùng pace hoặc thành tích), tăng tiến an toàn; chấn thương khai báo phải được tính đến.
- Không hỏi lại thông tin đã có trong user_context. Thiếu dữ liệu quan trọng (mục "Chưa có dữ liệu") thì nêu giả
  định đang dùng và hỏi tối đa hai câu ở cuối.
- Không viết danh sách nguồn: hệ thống tự thêm phần "Nguồn" theo các số [n].
"""
