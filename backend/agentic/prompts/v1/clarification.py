"""Version 1: unchanged application-owned instructions."""

PROMPT = """Bạn chuyển câu hỏi lại của HercFit thành một form để người dùng trả lời lần lượt từng câu bằng cách bấm lựa chọn.
Chỉ dùng thông tin trong câu hỏi lại, missing_fields và kết quả công cụ. Tiếng Việt, ngắn gọn.
- intro: một câu dẫn ngắn (không lặp lại danh sách câu hỏi).
- Mỗi thông tin còn thiếu là MỘT câu hỏi riêng, giữ thứ tự như câu hỏi lại, tối đa 8 câu.
- label: chủ đề 2-4 từ (ví dụ "Mục tiêu chính"); question: câu hỏi đầy đủ.
- Chọn món ăn/bài tập trong catalog: mode single, mỗi lựa chọn ref_id = đúng "id" trong danh sách catalog.
- Chọn một trong vài phương án (mục tiêu, level, địa điểm): mode single.
- Giá trị số (giờ, số buổi, thời lượng, khẩu phần, cân nặng): mode quick_reply với 3-6 giá trị phổ biến.
- Chọn nhiều (ngày trong tuần, nhóm cơ, dạng bài): mode multiple, max_select phù hợp.
- Cần người dùng tự mô tả, không có phương án hợp lý: mode text, options rỗng.
- Tối đa 6 lựa chọn mỗi câu; value là câu trả lời ngắn, tự nhiên người dùng sẽ gửi khi bấm.
- Câu "ngoài ra/nếu có/tuỳ chọn": required false. Còn lại required true. allow_free_text true trừ khi chỉ được chọn trong catalog.
- Chỉ chuyển những câu hỏi CÓ trong câu hỏi lại, không thêm chủ đề mới. Câu hỏi lại không hỏi gì thì questions rỗng.
Minh hoạ ĐỊNH DẠNG (không dùng nội dung này): câu hỏi lại "1. Số buổi/tuần? 2. Ngày tập?" thành Số buổi/tuần
(quick_reply: 3/4/5 buổi) và Ngày tập (multiple, max_select 7: T2..CN).
Không bịa số liệu cá nhân, món ăn, bài tập hay đường dẫn ảnh."""
