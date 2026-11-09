"""Thông báo trong ứng dụng: briefing buổi sáng, insight, lời khen, nhắc chất lượng dữ liệu.

Nội dung do code sinh từ đánh giá hằng ngày tất định (analytics/daily_health), không gọi LLM. Chỉ gửi
khi người dùng tự bật consent "proactive"; mỗi thông báo có dedup_key để không lặp, và có giới hạn
mỗi ngày cùng giờ yên lặng. Không có loại "khẩn cấp y khoa": trạng thái needs_review chỉ thành một
briefing trung tính trỏ về bảng sức khoẻ.
"""
