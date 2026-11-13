# Kết quả đánh giá đã lưu

Mỗi file là đầu ra nguyên văn của một lệnh eval, chạy trên commit sạch `95b2870a9506` (nhánh
`refactor/agent-architecture`, 2026-11-13). Chạy lại các lệnh dưới đây từ `backend/` cho cùng kết quả:
backtest dùng seed cố định, eval an toàn dùng model kịch bản. Đã chạy lại mỗi lệnh hai lần để kiểm: 0 khác biệt.

Biến môi trường cho mọi lệnh: `LANGFUSE_TRACING=false JEV_MODE=off JWT_SECRET_KEY=ci-only MODE=dev PYTHONPATH=../tests`.

| Thí nghiệm | File | Lệnh tái lập | Kết quả chính |
|---|---|---|---|
| E7 — bộ an toàn, chống prompt injection | `E7-safety-deterministic.md`, `.json` | `../.venv/bin/python -m evaluation safety --mode deterministic --out /tmp/e7` | 16 ca, PASS: 0 vi phạm an toàn cứng (ghi không xác nhận, truy cập chéo người dùng, tool bị cấm, ghi khi bị chặn); `injection_resisted` = 1.0; `safety_verdict` = 1.0 |
| E7 — tấn công Cypher vào context graph | `E7-cypher-safety.txt` | `../.venv/bin/python -m evaluation.kg_eval safety --offline` | 32/32 truy vấn tấn công bị validator từ chối; 4/4 truy vấn được viết lại gắn phạm vi người dùng |
| E8 — báo nhầm của luật readiness | `E8-readiness-backtest.md`, `.json` | `../.venv/bin/python -m evaluation.daily_health_backtest --scenarios` | 9 kịch bản tổng hợp × 55 ngày; báo nhầm ở ngày bình thường 0–18 %; bắt được 100 % ngày căng (quá tải, ngủ kém), 100 % ngày ốm, 100 % ngày thiếu dữ liệu |

Giới hạn:
- E7 ở đây dùng model kịch bản: nó đo phần do code sở hữu (cổng xác nhận, cô lập người dùng, chặn an toàn, danh sách tool
  được phép), không đo hành vi của model thật. Bản chạy với model thật là E2, cần duyệt chi phí.
- E7 Cypher chạy chế độ offline, chỉ kiểm lớp validator. Hai lớp còn lại (transaction chỉ đọc và lọc kết quả) cần Neo4j
  nên không chạy, để tránh đụng graph của dev.
- E8 dùng dữ liệu tổng hợp với nhãn do chính bộ sinh đặt: đây là kiểm tra tính nhất quán và tần suất báo của heuristic,
  không phải kiểm định lâm sàng.
