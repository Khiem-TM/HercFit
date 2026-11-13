# Đánh giá HercFit

Tài liệu này ghi kết quả tám thí nghiệm (E1–E8) của khoá luận. Mỗi mục gồm câu hỏi, cách đo, dữ liệu, kết quả, giới hạn
và lệnh tái lập. Số liệu chỉ lấy từ các lần chạy đã lưu trong `docs/evaluation/`; thí nghiệm chưa chạy được ghi rõ là
chưa chạy, không có số ước đoán.

Trạng thái ngày 2026-11-13:

| Mã | Câu hỏi | Trạng thái |
|---|---|---|
| E1 | Định tuyến chính xác đến đâu? | **Chưa chạy** — tốn phí, chờ duyệt (L6.3) |
| E2 | Cổng ghi có an toàn không? | Phần do code sở hữu: **đã đo** (tất định). Với model thật: chưa chạy, chờ duyệt |
| E3 | Model riêng từng agent có lợi gì? | **Chưa chạy** — tốn phí, chờ duyệt |
| E4 | Kỹ thuật truy hồi nào đáng giữ? | **Chưa chạy** — tốn phí, chờ duyệt |
| E5 | Context graph có hơn đọc backend theo mẫu không? | **Chưa chạy** — tốn phí, chờ duyệt; công cụ và dữ liệu đã sẵn sàng |
| E6 | Đường ghi nhanh cải thiện bao nhiêu? | **Chưa chạy** — cần số đo trước (L0.3) và sau, do người kiểm thử thao tác |
| E7 | Chống lạm dụng thế nào? | **Đã đo** |
| E8 | Luật readiness báo nhầm bao nhiêu? | **Đã đo** |

Môi trường chung cho mọi lệnh (chạy từ `backend/`):
`LANGFUSE_TRACING=false JEV_MODE=off JWT_SECRET_KEY=ci-only MODE=dev PYTHONPATH=../tests`. Lệnh live cần thêm khoá model
trong `.env` và cờ `--allow-paid`.

---

## E1 — Định tuyến

- **Câu hỏi:** router (model + luật code) giao đúng agent/hành động cho từng loại yêu cầu đến mức nào, và mỗi lượt tốn
  bao nhiêu lời gọi model?
- **Cách đo:** chạy graph thật với model thật. So tuyến của quyết định đầu tiên với tuyến kỳ vọng; báo routing accuracy,
  macro-F1, ma trận nhầm và số lời gọi LLM mỗi lượt. Lặp 3 lần, báo trung bình ± độ lệch chuẩn giữa các lần.
- **Dữ liệu:** 78 ca `e1_*` trong `tests/evaluation/datasets/agent_golden.jsonl`. Đó là tin nhắn của bộ ca chuẩn L4.1 đã
  bỏ kịch bản model; tuyến kỳ vọng là tuyến mà lần chạy tất định đã xác nhận.
- **Kết quả:** chưa chạy.
- **Lệnh:** `../.venv/bin/python -m evaluation agent --mode live --tags e1_routing --repeat 3 --allow-paid`
- **Giới hạn:** tuyến kỳ vọng do người viết ca đặt (qua kịch bản của bộ L4.1); vài ca có nhiều cách định tuyến hợp lý.

## E2 — An toàn của cổng ghi

- **Câu hỏi:** có lần ghi nào xảy ra mà người dùng chưa xác nhận, có truy cập chéo người dùng, có gọi tool bị cấm không?
  Ngưỡng chấp nhận: 0.
- **Cách đo:** evaluator tất định đọc lại trạng thái backend giả sau mỗi ca: lệnh ghi đã thực thi, người dùng của từng
  lời gọi, tool ngoài danh sách cho phép.
- **Kết quả (phần do code sở hữu, model kịch bản):** bộ ca chuẩn 88 ca và bộ an toàn 16 ca: **0 vi phạm an toàn cứng**.
  Các chỉ số `no_unconfirmed_write`, `user_isolation`, `no_forbidden_tool_executed`, `no_duplicate_write`,
  `no_write_on_safety_block` đều 1.0. Bằng chứng: `docs/evaluation/E7-safety-deterministic.md`; bộ 88 ca chạy trong
  `make -C tests check` ở mọi commit.
- **Chưa đo:** cùng các chỉ số với model thật (21 ca an toàn), lệnh
  `../.venv/bin/python -m evaluation safety --mode live --repeat 3 --allow-paid`.
- **Giới hạn:** model kịch bản cho biết code chặn được gì khi model đề xuất một lệnh, không cho biết model thật đề xuất
  gì.

## E3 — Model riêng từng agent

- **Câu hỏi:** gán model nhỏ cho từng agent chuyên trách có giữ được độ chính xác trong khi giảm độ trễ và token không?
- **Cách đo:** mỗi agent chạy trên prompt, schema tool và luật code thật của nó với từng model; báo pass rate, tỷ lệ
  output hợp lệ, độ trễ p50/p90, token theo (agent, model).
- **Dữ liệu:** 83 ca (supervisor 26, health_safety 20, nutrition 5, training_log 5, synthesizer 5, body_health 4,
  daily_health 4, coach 4, research 4, clarify 3, memory 3) × 8 model.
- **Kết quả:** chưa chạy trên commit hiện tại.
- **Lệnh:** `../.venv/bin/python -m evaluation.agent_model_eval --repeat 3 --out eval_results/agent_models`
- **Giới hạn:** nhiều agent có dưới 50 ca: kết quả theo agent là **quan sát sơ bộ**.

## E4 — Kỹ thuật truy hồi

- **Câu hỏi:** vector, BM25, hybrid hay hybrid + rerank cho tài liệu đúng nhất?
- **Cách đo:** recall@k và MRR trên 87 truy vấn có tài liệu đúng đã gán nhãn; faithfulness của câu trả lời qua Ragas.
- **Kết quả:** chưa chạy trên commit hiện tại.
- **Lệnh:** `../.venv/bin/python -m evaluation rag --allow-paid --variants vector bm25 hybrid hybrid_rerank`
- **Giới hạn:** nhãn tài liệu đúng do người viết đặt; faithfulness phụ thuộc model chấm.

## E5 — Nguồn ngữ cảnh cá nhân

- **Câu hỏi:** thêm context graph có giúp trả lời câu hỏi về dữ liệu của chính người dùng đúng hơn so với chỉ đọc
  backend theo mẫu không, và tốn thêm bao nhiêu độ trễ, token?
- **Cách đo:** chạy graph thật với model thật trên người dùng tổng hợp của `kg_eval` (có dữ liệu seed tất định). Mỗi
  câu hỏi chạy với ba cấu hình `CONTEXT_SOURCES`: `card` / `card+backend_reads` / `card+backend_reads+context_graph`.
  Câu trả lời đúng khi chứa mọi nhóm chuỗi kỳ vọng (không phân biệt dấu). Lặp 3 lần.
- **Dữ liệu:** 33 câu hỏi có đáp án (`context_cases.jsonl`: 14 ca cũ + 19 ca mới; đáp án suy từ dữ liệu seed) và 20 ca
  định tuyến cá nhân (`personalization_cases.jsonl`).
- **Đã kiểm (tất định, không tốn phí):** mỗi cấu hình chỉ chạm đúng nguồn của nó. Thẻ hồ sơ được nạp ở cả ba cấu hình;
  context graph chỉ chạy ở cấu hình thứ ba (50/66 lượt; các lượt còn lại đi lối tắt đọc nhanh, không qua router); sự kiện
  KG kiểu cũ tắt ở cả ba.
- **Kết quả về độ đúng:** chưa chạy.
- **Lệnh:** `../.venv/bin/python -m evaluation.context_sources_eval --mode live --allow-paid --repeat 3 --out eval_results/e5`
  (`--dry-run` in kế hoạch và ước lượng).
- **Giới hạn:** chuỗi kỳ vọng kiểm sự có mặt của con số/tên món, không kiểm lập luận; dưới 50 ca có đáp án: kết quả là
  **quan sát sơ bộ**.

## E6 — Đường ghi nhanh

- **Câu hỏi:** sau Phase 3 (ghi bữa ăn bằng code, lệnh ghi đơn giản, biên nhận ngay), thời gian và số lời gọi model của
  6 kịch bản ghi giảm bao nhiêu?
- **Cách đo:** người kiểm thử lặp lại 6 kịch bản của L0.3 trên giao diện; số liệu lấy từ trace Langfuse.
- **Kết quả:** chưa có. Cần số đo trước (L0.3, người phụ trách chạy sau) và số đo sau.
- **Đã đo (tất định):** số lời gọi model của các đường ghi do code dựng được khoá bằng cổng `model_calls`. Ví dụ: ghi
  bữa ăn có bản nháp 1 lời gọi router và 0 lời gọi tool model; lệnh ghi đơn giản 0 lời gọi model; biên nhận sau khi duyệt
  0 lời gọi model.

## E7 — Chống lạm dụng

- **Câu hỏi:** hệ thống chặn được yêu cầu nguy hiểm, prompt injection và truy vấn Cypher độc hại tới mức nào?
- **Kết quả (commit `95b2870`):**

  | Bộ | Số ca | Kết quả |
  |---|---|---|
  | Bộ an toàn (tự hại, thâm hụt năng lượng cực đoan, triệu chứng nguy hiểm, cảnh báo y tế, injection đòi xoá dữ liệu, cô lập người dùng, tool bị cấm, ngân sách tool) | 16 | 0 vi phạm an toàn cứng; `safety_verdict` 1.0; `injection_resisted` 1.0 |
  | Truy vấn Cypher tấn công (ghi, gọi procedure, LOAD CSV, UNION, nhiều câu lệnh, nhãn lạ, sở hữu người khác, đọc thuộc tính nội bộ, subquery, đường đi không giới hạn...) | 32 | 32/32 bị validator từ chối |
  | Truy vấn hợp lệ cần gắn phạm vi người dùng | 4 | 4/4 được viết lại có phạm vi |

- **Lệnh:** `../.venv/bin/python -m evaluation safety --mode deterministic` ·
  `../.venv/bin/python -m evaluation.kg_eval safety --offline`
- **Giới hạn:** bộ an toàn dùng model kịch bản (đo phần do code sở hữu). Cypher chỉ chạy lớp validator; hai lớp sau
  (transaction chỉ đọc, lọc kết quả) cần Neo4j, chưa chạy.

## E8 — Báo nhầm của luật readiness

- **Câu hỏi:** engine readiness và bộ luật cảnh báo chỉ số báo nhầm bao nhiêu ở ngày bình thường, và bắt được bao nhiêu
  ngày có vấn đề?
- **Cách đo:** backtest trên 9 kịch bản tổng hợp × 55 ngày, mỗi ngày đánh giá như lúc 08:00; nhãn do bộ sinh đặt.
- **Kết quả (commit `95b2870`, seed 7):**

  | Kịch bản | Báo nhầm ở ngày bình thường | Bắt đúng |
  |---|---|---|
  | baseline_normal | 11 % | — |
  | overreaching | 8 % | 100 % ngày căng |
  | illness_onset | 12 % | 100 % ngày ốm |
  | poor_sleep_week | 10 % | 100 % ngày căng |
  | irregular_sleep | 13 % | — |
  | improving | 11 % | — |
  | missing_data | 18 % | 100 % ngày thiếu dữ liệu → insufficient |
  | manual_sleep_only | 0 % | — |
  | new_user | 0 % | 100 % ngày thiếu dữ liệu → insufficient |

- **Lệnh:** `../.venv/bin/python -m evaluation.daily_health_backtest --scenarios`
- **Giới hạn:** dữ liệu và nhãn tổng hợp: đây là kiểm tra tính nhất quán và tần suất báo của heuristic, **không** phải
  kiểm định lâm sàng. Ở 7/9 kịch bản có dữ liệu thiết bị, 8–18 % ngày bình thường bị báo nhầm: đây là kết quả âm cần nêu
  trong luận văn. Hai kịch bản 0 % là hai kịch bản ít dữ liệu (chỉ giấc ngủ ghi tay, người dùng mới).

---

## Bảng quyết định giữ / tắt

Quy tắc: thành phần không tốt hơn baseline ở E4 hoặc E5 thì đề xuất tắt khỏi đường chạy chính. Agent chỉ đề xuất;
người phụ trách điền cột "Quyết định". Bảng này là đầu vào của L7.1.

| Thành phần | Thí nghiệm | Baseline so sánh | Số liệu | Đề xuất của agent | Quyết định |
|---|---|---|---|---|---|
| Context graph (nguồn `context_graph`) | E5 | `card+backend_reads` | chưa có | Chưa đủ số liệu; giữ cho tới khi E5 chạy | |
| Đọc backend của nút context (`backend_reads`) | E5 | `card` | chưa có | Chưa đủ số liệu; giữ | |
| Sự kiện KG kiểu cũ (`kg_facts`) | không có thí nghiệm riêng | — | — | Không có số liệu để đề xuất tắt; giữ | |
| Rerank (`hybrid_rerank`) | E4 | `hybrid` | chưa có | Chưa đủ số liệu; giữ | |
| BM25 trong hybrid | E4 | `vector` | chưa có | Chưa đủ số liệu; giữ | |
