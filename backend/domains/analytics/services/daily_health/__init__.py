"""Daily Health Intelligence: phân tích sức khoẻ hằng ngày tất định (snapshot, đường nền, độ lệch, độ sẵn sàng).

baseline   đường nền cá nhân dùng chung (trung vị + MAD) cho mọi nơi so với "bình thường của bạn"
analytics  hàm thuần: snapshot của ngày, độ lệch so với nền, xu hướng 7 ngày, chất lượng dữ liệu
readiness  luật quyết định có phiên bản: trạng thái sẵn sàng, lý do, độ tin cậy, khuyến nghị
service    đọc health_points/nhật ký tập rồi gọi các hàm thuần (không lưu gì, tính lúc đọc)

LLM không tính lại con số nào ở đây và không chẩn đoán: nó chỉ diễn giải kết quả đã có nguồn.
"""
