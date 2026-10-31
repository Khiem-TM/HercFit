# Kế hoạch ingest Lore of Running, 4th edition

> Hồ sơ lần nạp đầu (pipeline `paginated-ocr-e5-v2`). Thư mục `knowledge-ingestion/` nhắc tới
> bên dưới nay là `backend/knowledge_ingestion/` (dữ liệu trong `data/`); quy trình hiện hành ở README.

Ngày lập: 29/10/2026. Mục tiêu: chuẩn bị và nạp sách vào schema `knowledge_*`
hiện có của PostgreSQL/pgvector, dùng FPT `multilingual-e5-large`.

## Dữ liệu và quyết định xử lý

- Nguồn: `../409543317-Lore-of-Running-4th-ed-pdf.txt`, 3.125.485 byte,
  3.122.023 ký tự trước chuẩn hoá và 946 trang vật lý phân cách bằng form feed.
- SHA-256 nguồn: `6453efb0e72f0651fc4bb03d14494583611fc939f80974eb5fa59297f37f3e07`.
- Chọn trang nguồn 16–934: nội dung 15 chương; bỏ phần đầu sách và index/quảng cáo
  cuối sách. Trang 269 là trang ảnh bị OCR thành ký tự nhiễu, được loại riêng.
- Giữ các phần giới thiệu II/III/IV, dùng tiêu đề chuẩn từ mục lục để thay cho
  tiêu đề OCR bị hỏng. Không tự sửa thuật ngữ, kết luận, liều lượng hay số liệu.
- Đánh dấu trang mở chương/phần để kiểm tra thủ công. Báo cáo còn 18 trang được
  gắn cờ này. Hai trang không có nội dung sau xử lý được bỏ qua.
- Chia theo từng trang để giữ nguồn trích dẫn chính xác. Mục tiêu overlap 64 token
  bên trong một trang, không ghép nội dung khác chương hoặc khác trang.

## Kết quả chuẩn bị đã chạy

| Chỉ số | Giá trị |
| --- | ---: |
| Trang có nội dung được giữ | 916 |
| Ký tự sau làm sạch | 2.733.104 |
| Chunk | 1.877 |
| Token lớn nhất/chunk, gồm passage prefix và special tokens | 476 |
| Tổng token đầu vào embedding theo tokenizer local | 719.363 |
| Batch dự kiến với batch size 8 | 235 |
| Số chiều/vector | 1.024 |

Token local dùng để kiểm soát độ dài, không phải cam kết số token FPT tính phí.
Không có ước tính thời gian cố định; thời gian phụ thuộc latency, quota và retry.
Vector float32 có payload thô khoảng 7,7 MB cho sách này, chưa tính overhead bảng,
index, metadata, nội dung văn bản và các revision.

## Trình tự thực thi

1. **Prepare — đã thực hiện.** Giữ file nguồn nguyên vẹn; chuẩn hoá Unicode,
   nối dòng/từ ngắt, xử lý drop caps và bỏ nhiễu đã xác định. Xuất cleaned text,
   chunk JSONL, manifest và báo cáo có checksum.
2. **Validate — đã thực hiện.** Kiểm tra checksum, số lượng/thứ tự chunk,
   nội dung có trong bản sạch và độ dài bằng tokenizer E5 thật. Xem mẫu ở chương
   1, 2, 5, 7, 10 và 15; kiểm tra thêm các trang được gắn cờ trước khi approve.
3. **Preflight — đã thực hiện.** Khóa FPT mới trong `backend/agentic/.env` gọi
   được endpoint `https://mkp-api.fptcloud.com/embeddings`; query và passage đều
   trả 1.024 chiều. DB local có pgvector `0.8.7` và các bảng ingestion cần thiết.
4. **Enqueue — đã hoàn tất trên DB ứng dụng.** Revision hiện dùng:
   `63802e45-22ca-4ff4-9394-cfd2e412ebee`, gồm 1.877 chunk.
5. **Embed — đã hoàn tất.** FPT đã tạo đủ 1.877 vector thật, job `INDEXED`
   ngay lần chạy đầu tiên. Vector 1.024 chiều, chuẩn hoá L2; không có lỗi ghi nhận.
6. **Verify — đã hoàn tất.** Đủ 1.877 chunk và 1.877 embedding của đúng
   profile; min/max dimension đều 1.024; norm nằm trong
   `[0.999999970, 1.000000030]`. Đã rà soát mẫu mở đầu các trang gắn cờ và sửa
   lỗi OCR drop cap/preamble trước khi tạo vector.
7. **Publish — đã hoàn tất theo yêu cầu người dùng.** Revision `APPROVED`,
   là active revision của tài liệu; profile embedding đã active. Đã bật RAG và
   đồng bộ model/endpoint/key/revision ở backend, agentic; recreate hai service.
   Cả hai service healthy. Đã thử trực tiếp adapter RAG của agent với API backend
   đang chạy bằng ba truy vấn Việt/Anh, đều trả nội dung sách có nguồn và trang.

Lệnh cụ thể và cấu hình nằm trong README. Không cần đổi schema hay thêm ANN index
để chạy thử quy mô một sách này; retrieval hiện có dùng cosine + full-text search.
Việc tăng tốc cho corpus lớn là một thay đổi riêng sau khi đo truy vấn thực tế.

## Kiểm thử đã thực hiện

- 22 test offline: làm sạch giữ số/đơn vị/trang/bảng, token budget trên nhiều ngôn
  ngữ, checksum/idempotence, chặn path traversal, prefix query/passage, auth header,
  vector invalid, HTTP 429 retry/401 không retry, tái dùng vector đã có.
- 1 test integration trên database tạm riêng: enqueue lặp không nhân dữ liệu,
  lưu vector giả lập, chạy lại job không gọi embedding thừa, kiểm tra coverage,
  và luồng review/approve/activate. Database test đã được xoá sau kiểm tra.
- Preflight FPT thật với hai câu mẫu và kiểm tra schema pgvector chỉ đọc.
- Bulk embedding đã hoàn tất và đã xác minh retrieval thực tế (smoke check,
  không phải benchmark chất lượng toàn diện). Truy vấn overtraining trả chương 7,
  câu hỏi về điều hoà thân nhiệt trả chương 4 ở vị trí đầu tiên.
- Bản nháp đầu tiên `ab0a3b38-1bea-4bd6-a958-650eefa051c7` được giữ lại ở
  trạng thái `REJECTED`; job được đánh dấu `ReplacedBeforeIndexing` do sửa lỗi OCR
  trước khi gửi dữ liệu cho FPT. Bản nháp này không có vector và không được tìm kiếm.

## Tài liệu tham chiếu

- FPT API: https://github.com/fpt-corp/ai-marketplace/blob/main/API%20Integration%20-%20Embedding%20Model.md
- E5 model card: https://huggingface.co/intfloat/multilingual-e5-large
- Tokenizer pin: `intfloat/multilingual-e5-large` tại
  `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`.

Model card quy định prefix `query:`/`passage:`, vector 1.024 chiều và giới hạn
512 token. Pipeline chọn budget 480 thay vì phụ thuộc vào thông số context của
catalog gateway; mọi chunk được đếm và xác thực trước khi enqueue.

## Hồ sơ thực thi

- Hoàn tất: 29/10/2026, 15:57 (Asia/Ho_Chi_Minh).
- Model: `multilingual-e5-large`; revision cấu hình: `e5-prefix-v1`.
- Profile: `641c5dc72733916fcfe6b8c72d5f7e40cbdf2a0cd46eaa7a55b64d97eea8c805`.
- Job: `a03259f6-a8e2-4bc0-bdb0-1ce44f47fa31`; attempts: 1.
- Chi tiết DB: `knowledge-input/lore-of-running/execution.json`.
- Kết quả API/adapter: `knowledge-input/lore-of-running/retrieval-check.json`.
- API không có token vẫn trả 401. Không lưu token đăng nhập hoặc API key trong
  các hồ sơ này.
