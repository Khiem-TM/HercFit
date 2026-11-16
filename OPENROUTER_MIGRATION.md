# Chuyển nhà cung cấp LLM: FPT AI Factory → OpenRouter

Tài liệu vận hành cho người phát triển HercFit: cấu hình, chính sách model/endpoint, cách kiểm định và cách đổi
profile RAG. Kết quả đánh giá chi tiết nằm ở `docs/OPENROUTER_EVALUATION.md` (thư mục `docs/` chỉ giữ cục bộ).

## 1. Cấu hình

| Biến | File | Ghi chú |
|---|---|---|
| `OPENROUTER_API_KEY` | `backend/.env` | Khoá dùng chung cho agent, RAG (embedding + rerank), catalog, ingestion và Ragas |
| `OPENROUTER_BASE_URL` | `backend/.env` | Mặc định `https://openrouter.ai/api/v1` |
| `DEFAULT_PROVIDER=openrouter`, `DEFAULT_MODEL`, `AGENT_MODELS` | `backend/agentic/.env` | Xem bảng model bên dưới |
| `EMBEDDING_MODEL`, `EMBEDDING_REVISION`, `RERANK_MODEL`, `RERANK_PATH` | `backend/.env` | Không đặt `EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY`: mặc định dùng base và khoá OpenRouter |
| `RAG_MIN_RERANK_SCORE`, `RAG_MIN_DENSE_SIMILARITY`, `RAG_CALIBRATED_PROFILE` | `backend/.env` | Ngưỡng đã hiệu chỉnh cho đúng profile; `activate` từ chối khi thiếu |

Biến môi trường của tiến trình luôn thắng file `.env`. Container Compose nhận biến lúc **tạo**, nên sau khi sửa `.env`
phải tạo lại container (`docker compose up -d --no-deps agentic kg-worker backend`), không chỉ chờ hot-reload.
`tokenizers` (kiểm tra giới hạn 512 token của E5 khi truy vấn) cần image mới: `docker compose build agentic kg-worker`.

## 2. Model và endpoint

Mọi model phải có chính sách endpoint đã kiểm duyệt trong `backend/agentic/core/providers/openrouter_policy.py`;
model lạ bị từ chối ngay khi dựng client, không bao giờ để OpenRouter tự chọn host mới. Mỗi request gửi
`provider.only`, `provider.order`, `require_parameters: true`.

| Vai trò | FPT (cũ) | OpenRouter | Endpoint (thứ tự) | Reasoning |
|---|---|---|---|---|
| Mặc định (định tuyến, tool, trả lời, research) | DeepSeek-V4-Flash | `deepseek/deepseek-v4-flash` | `fireworks` → `azure/us` | `high`; catalog `none` |
| nutrition, memory | gemma-4-26B-A4B-it | `google/gemma-4-26b-a4b-it` | `primeintellect/bf16` → `deepinfra/fp8` | tắt |
| body_health, clarify, context, ảnh catalog | gemma-4-31B-it / Qwen2.5-VL-7B | `google/gemma-4-31b-it` | `novita/bf16` → `deepinfra/fp8` | tắt |
| Judge Ragas | Llama-3.3-70B | `meta-llama/llama-3.3-70b-instruct` | `akashml/fp8` | — |
| Embedding | multilingual-e5-large | `intfloat/multilingual-e5-large` | `deepinfra/fp32` | — |
| Rerank | bge-reranker-v2-m3 | `cohere/rerank-v3.5` | `cohere` | — |

DeepSeek trên OpenRouter chỉ có mức reasoning `high`/`xhigh`/`none` (FPT có `low`/`medium`), nên các effort theo vai
trò/chế độ đã bỏ; timeout tăng tương ứng (routing 30 s, tool 60 s, trả lời 90 s, research 60 s, lượt 180 s, Plan 300 s).

**Vì sao không dùng DeepInfra cho DeepSeek:** probe ngày 16/11 với 64 lời gọi `RouteDecision` bắt buộc cho thấy
DeepInfra trả tool call có `arguments` rỗng ở 23/64 lần (cả khi tắt reasoning), trong khi Fireworks 47/48 và Azure
23/24 hợp lệ. Parasail, GMI, SiliconFlow không hỗ trợ `tool_choice` bắt buộc (404). Probe tái lập:
`backend/eval_results/openrouter-migration/probe_route.py <n> [effort|-] [endpoint]`.

## 3. Hành vi adapter (`core/providers/openrouter.py`)

- Chat Completions API tường minh; không viết lại payload kiểu FPT (gộp system, ép `required`, khôi phục DSML, quy
  đổi usage luỹ kế). Markup DSML lọt vào văn bản chỉ bị lọc khỏi câu trả lời (`tool_markup.py`), không bao giờ thực thi.
- Không host nào nhận `parallel_tool_calls`, nên adapter tự áp dụng `parallel_tool_calls=False`: phản hồi có nhiều
  tool call chỉ giữ call đầu tiên (trước đây báo lỗi và làm hỏng 7/234 lượt E1 ở coach/training_log); arguments sai
  định dạng JSON là lỗi. Lỗi sau khi đã gửi header (lỗi giữa stream, stream không kết thúc) là lỗi, không phải câu
  trả lời rỗng.
- Output có cấu trúc không hợp lệ (arguments rỗng/sai schema) được **lấy mẫu lại một lần** khi client cho phép retry;
  model riêng của agent (`retries=0`) không lấy mẫu lại mà nâng lên model của vai trò như trước. Timeout và lỗi HTTP
  chỉ theo retry của SDK, nên đuôi độ trễ không nhân đôi.
- `reasoning`/`reasoning_details` được giữ trong `additional_kwargs` và gửi lại trong vòng tool, không bao giờ thành
  nội dung hiển thị.
- Chi phí: dùng `usage.cost` OpenRouter tính thật cho từng request (`openrouter_cost`, `openrouter_generation_id`
  trên span Langfuse, `model_requests` trong telemetry). `MODEL_PRICES` chỉ còn là ước tính (`llm_estimated_cost`)
  cho request thiếu `cost`, không bao giờ thay số tính phí.

## 4. Kiểm định trước khi bật

```bash
cd backend
# Chỉ đọc: xác thực khoá + endpoint có tool/tool_choice
MODE=dev ../.venv/bin/python -m agentic.scripts.openrouter_preflight
# Probe trả phí nhỏ (tool calling 4 model, stream, ảnh, embedding, rerank), dữ liệu tổng hợp
MODE=dev ../.venv/bin/python -m agentic.scripts.openrouter_preflight --live --allow-paid
```

Eval chấp nhận (từ `backend/`, `MODE=dev JEV_MODE=off PYTHONPATH=../tests`): E1
`python -m evaluation agent --mode live --tags e1_routing --repeat 3 --allow-paid --trace`, E2
`python -m evaluation safety --mode live --repeat 3 --allow-paid --trace`, so với baseline FPT bằng
`python3 eval_results/openrouter-migration/compare.py FPT=<run> OpenRouter=<run>`.

## 5. Đổi profile RAG

`profile_id` băm từ base URL, model, revision và số chiều; vector của hai profile không bao giờ được so sánh, và
`search()` từ chối khi profile active khác profile cấu hình (`RAG_PROFILE_NOT_READY`, nghiên cứu chuyển sang web).

```bash
cd backend && export MODE=dev JEV_MODE=off LANGFUSE_TRACING=false PYTHONPATH=.:../tests
../.venv/bin/python -m agentic.embedding.ingestion.cli reindex         # xếp hàng index cho profile mới
../.venv/bin/python -m agentic.embedding.ingestion.cli worker --once   # embed (1.762 chunk ≈ 0,01 USD)
# Đo trên profile mới khi chưa active (chỉ trong tiến trình eval, không ghi DB):
W=eval_results/openrouter-migration/candidate_profile.py
../.venv/bin/python $W evaluation.rag_eval retrieval --label cal --multi --rerank --options '{"thresholds": false}'
../.venv/bin/python -m evaluation.rag_eval calibrate eval_results/rag/<run> --score top_score
../.venv/bin/python -m evaluation.rag_eval calibrate eval_results/rag/<run> --score top_similarity
# Ghi RAG_MIN_RERANK_SCORE, RAG_MIN_DENSE_SIMILARITY, RAG_CALIBRATED_PROFILE=<profile_id> vào backend/.env, rồi:
../.venv/bin/python -m agentic.embedding.ingestion.cli activate
```

Ngưỡng của reranker cũ (bge, 0,20) không dùng lại được cho Cohere: hai reranker có thang điểm khác nhau. Giá trị đã
hiệu chỉnh ngày 16/11 cho profile `f323dd68…` (đang active trên dev): `RAG_MIN_RERANK_SCORE=0.51`,
`RAG_MIN_DENSE_SIMILARITY=0.83`.

## 6. Khôi phục

Bản `.env` trước khi chuyển nằm ở `backend/.cache/openrouter-migration/before-claude/` (quyền 600, bị Git bỏ qua).
Profile RAG cũ
vẫn còn trong DB nhưng cần FPT để embed truy vấn, nên chỉ khôi phục được cùng khoá FPT còn hạn mức.
