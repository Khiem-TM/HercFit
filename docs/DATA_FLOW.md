# Dữ liệu của bạn đi đâu

HercFit dùng sáu dịch vụ bên ngoài. Bảng dưới đây cho biết dữ liệu nào được gửi tới từng dịch vụ, để làm gì và đã
được che hay lược bớt những gì trước khi gửi. Mọi điều ghi ở đây được kiểm lại với mã nguồn (đường dẫn ở cột cuối).

| Dịch vụ | Dữ liệu được gửi | Mục đích | Đã che / lược bớt | Mã nguồn |
|---|---|---|---|---|
| **FPT AI Marketplace** (model ngôn ngữ, mặc định DeepSeek/Gemma) | Tin nhắn của lượt này và một cửa sổ hội thoại gần nhất; kết quả các lệnh đọc dữ liệu của chính bạn trong lượt (bữa ăn, buổi tập, số đo, tiến độ); thẻ hồ sơ tóm tắt (tuổi, giới tính, cân nặng, chiều cao, mục tiêu, số liệu tập luyện) ở chế độ Plan; khi bạn đã cho phép trợ lý dùng dữ liệu thiết bị: số liệu Google Health (bước chân, giấc ngủ, nhịp tim) | Hiểu yêu cầu, chọn công cụ, viết câu trả lời và lời thông báo | Không gửi token đăng nhập hay ID nội bộ trong nội dung. Dữ liệu sức khoẻ **không** bị che vì model cần nó để trả lời. Dữ liệu thiết bị chỉ được đọc khi bạn bật chia sẻ với trợ lý. Lời thông báo chỉ nhận thể trạng ở mức tóm tắt (giới tính, tuổi, mục tiêu), không nhận họ tên, email hay ngày sinh | `agentic/agents/`, `agentic/services/personal_context.py`, `agentic/agents/workflow.py` (`context_step`), `domains/notifications/services/composer.py` (`profile_summary`) |
| **Tavily** (tìm kiếm web) | Một câu hỏi kiến thức công khai do HercFit tự rút ra từ yêu cầu của bạn, ví dụ "tác dụng của creatine" | Tìm nguồn đã kiểm chứng cho câu trả lời kiến thức và cho tra cứu bài tập mới | Số đo của bạn (kg, cm, tuổi, kcal, bpm) bị xoá khỏi câu hỏi. Câu hỏi chứa email, số điện thoại, token, đường link, họ tên hay email của bạn thì bị từ chối, không gửi. Không gửi lịch sử hội thoại hay dữ liệu cá nhân | `agentic/services/route_rules.py` (`public_question`), `agentic/security/input_guard.py` (`safe_query`, `public_queries`), `agentic/agents/research_agent.py` |
| **Jev** (cổng kiểm định qua gateway LiteLLM; chỉ khi `JEV_MODE` khác `off`) | Cổng định tuyến: chỉ tin nhắn mới nhất của bạn. Cổng kiểm chứng tra cứu: đoạn trích nguồn công khai đã tìm được và bản nháp câu trả lời | Kiểm tra lệnh đọc nhanh có đúng ý không; kiểm tra câu trả lời có bám nguồn không | Cổng định tuyến không nhận lịch sử, hồ sơ hay ID; email, số điện thoại, UUID, token trong tin nhắn bị thay bằng nhãn. Payload gửi Jev bỏ các khoá định danh (user_id, session_id, email, phone, họ tên...) và che email/số điện thoại trong văn bản. HercFit chỉ lưu metadata của lần đánh giá, không lưu nội dung | `agentic/agents/adaptive_router.py` (`jev_routing_projection`), `agentic/services/jev.py`, `agentic/agents/research_agent.py` (`evidence_projection`, `evaluate`) |
| **Langfuse** (truy vết vận hành; chỉ khi `LANGFUSE_TRACING=true`) | Vết các bước của một lượt: prompt, câu trả lời, tool đã gọi, độ trễ, số token, chi phí | Gỡ lỗi, đo chất lượng và chi phí | ID người dùng được thay bằng bí danh HMAC. Token, cookie, khoá API, chuỗi kết nối, ảnh, vector bị xoá. Họ tên, email, số điện thoại, địa chỉ bị che. Số đo cơ thể, chỉ số sinh lý (BMR/TDEE, nhịp tim), tuổi, chấn thương bị che cả trong trường có cấu trúc lẫn văn bản tự do. Dinh dưỡng món ăn vẫn hiển thị. `LANGFUSE_CAPTURE_MODE=metadata_only` chỉ gửi metadata, không gửi nội dung | `agentic/observability/privacy.py`, `agentic/observability/langfuse_adapter.py`, `agentic/observability/settings.py` |
| **Google Health** (chỉ khi bạn kết nối) | HercFit đọc: bước chân, phút vận động, giấc ngủ, nhịp tim, buổi tập và số đo từ thiết bị. HercFit ghi: các bản ghi bạn tự nhập (cân nặng, chiều cao, % mỡ, nước uống, giấc ngủ, buổi tập), đẩy lên sau khi đã lưu trong HercFit | Hiển thị và phân tích dữ liệu thiết bị; giữ Google Health đồng bộ với những gì bạn ghi | Token OAuth được mã hoá khi lưu (`TOKEN_ENCRYPTION_KEY`). Phạm vi xin cấp: openid, email và các phạm vi sức khoẻ (đọc; ghi cho loại dữ liệu HercFit ghi). Khi xoá tài khoản, quyền được thu hồi tại Google trước | `integrations/google_health/` (`oauth.py`, `pull.py`, `push.py`, `tokens.py`), `domains/identity/services/privacy_service.py` |
| **Cloudinary** (lưu ảnh) | Ảnh bạn tải lên hoặc nhập từ link cho bữa ăn, buổi tập, món và bài tập riêng | Lưu và phục vụ ảnh | Ảnh được giải mã và kiểm tra kích thước ở server trước khi tải lên. Tải lên chỉ từ server (khoá API không tới trình duyệt). Khi xoá tài khoản, ảnh được xếp hàng xoá trên Cloudinary | `domains/media/services/cloudinary_images.py`, `domains/media/services/image_cleanup.py`, `domains/identity/services/privacy_service.py` (`IMAGE_TABLES`) |

## Những gì không rời khỏi HercFit

- Mật khẩu: HercFit không có mật khẩu; đăng nhập bằng Google OAuth.
- Token phiên (access/refresh) và token uỷ quyền của trợ lý không bao giờ nằm trong prompt, vết hay payload gửi ra
  ngoài.
- Cơ sở dữ liệu (PostgreSQL, Neo4j) chạy trong hạ tầng của HercFit. Service trợ lý dùng role database chỉ có quyền
  trên bảng của chính nó (`backend/scripts/db_roles.sql`), đọc dữ liệu nghiệp vụ qua API của backend.

## Quyền của bạn

- **Xuất dữ liệu:** Cài đặt → Xuất dữ liệu (`GET /api/profile/export`).
- **Xoá tài khoản:** Cài đặt → Xoá tài khoản (`POST /api/profile/erase`). Backend xoá mọi cuộc trò chuyện ở service
  trợ lý trước; nếu chưa xoá được, tài khoản giữ nguyên và bạn được báo thử lại. Sau đó tài khoản, nhật ký, số đo,
  kết nối Google Health bị xoá; ảnh được xếp hàng xoá trên Cloudinary.
- **Dữ liệu thiết bị:** chỉ được trợ lý dùng khi bạn bật chia sẻ trong Cài đặt → Kết nối; tắt bất cứ lúc nào.
- Export/erase và lịch sử chat chỉ dành cho phiên đăng nhập của chủ tài khoản; token uỷ quyền của trợ lý bị từ chối.
- Transcript giữ độc lập với checkpoint và summary. Thu hồi consent xoá ngữ cảnh model, giữ cuộc trò chuyện để bạn
  xem hoặc tự xoá. Chi tiết vòng đời, xử lý lỗi và migration: [Bộ nhớ hội thoại](MEMORY_LIFECYCLE.md).
