# RAG document ingestion

Chuẩn bị tài liệu, nạp chunk, tạo embedding và vận hành job cho kho tài liệu RAG.
Backend giữ API tìm kiếm (`embedding/`) và schema PostgreSQL (`alembic/`).

Git theo dõi code, spec trong `manifests/` và SQL kiểm tra trong `sql/`. Sách nguồn, bundle
đã chuẩn bị và cache tokenizer nằm trong `data/` (bị ignore). `tests/` cũng bị ignore theo
quy ước chung của repo. Hồ sơ lần nạp đầu (pipeline v2): [PLAN.md](PLAN.md).

```
data/
  sources/   sách/tài liệu gốc (không versioned, có bản quyền)
  input/     bundle đã prepare: cleaned.txt, chunks.jsonl, manifest.json, report.json
  .cache/    tokenizer E5 đã pin revision
```

## Chạy nhanh (từ `backend/`)

```sh
uv pip install --python ../.venv/bin/python -r knowledge_ingestion/requirements.txt
export PYTHONPATH=.
../.venv/bin/python -m knowledge_ingestion.cli --help
../.venv/bin/python -m knowledge_ingestion.cli fetch-tokenizer
../.venv/bin/python -m knowledge_ingestion.cli prepare knowledge_ingestion/data/sources/<file>.txt
../.venv/bin/python -m knowledge_ingestion.cli validate knowledge_ingestion/data/input/lore-of-running/manifest.json
../.venv/bin/python -m knowledge_ingestion.cli preflight
```

`prepare` và `validate` chạy offline (không gọi API, không mở DB). `preflight` gọi thật
embedding (query và passage) và rerank, chỉ in model, số chiều, endpoint, profile ID.
Thêm `LANGSMITH_TRACING=false LANGSMITH_ENABLED=false` để tắt tracing cho một lệnh.

## Cấu hình

Thứ tự ưu tiên từ thấp đến cao: `backend/.env` → `backend/agentic/.env` →
`backend/knowledge_ingestion/.env` → biến môi trường. Xem `.env.example`.
`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` được ưu tiên hơn `FPT_BASE_URL`/`FPT_API_KEY`.

Profile embedding = hash(endpoint, model, `EMBEDDING_REVISION`, số chiều). Backend chỉ trả
kết quả khi profile của nó trùng profile đang active trong DB.

## Pipeline chuẩn bị (`chapter-stream-ocr-e5-v3`)

- `cleaning.py`: Unicode NFKC, ký tự điều khiển, drop cap, từ ngắt dòng, margin lặp; giữ
  số, đơn vị, dòng bảng/danh sách. Không dùng LLM sửa nội dung.
- `preparation.py`: các trang **liên tiếp trong cùng một chương** được nối thành một dòng văn
  bản; câu chạy qua ngắt trang được nối bằng dấu cách, từ bị gạch nối qua trang được ghép lại.
  Chunk không vượt ranh giới chương. Mỗi chunk có `page`, `page_end` (trang vật lý trong file
  nguồn) và `page_label` (trang in, tính từ `printed_page` của chương trong spec theo mục lục).
- **Contextual header**: worker embed `"<title> — <chương>\n<đoạn>"`; cột `content` giữ
  nguyên đoạn gốc nên trích dẫn và kiểm tra quote không đổi. Token của header được tính vào
  ngân sách 480 token (`tokenization.py`, tokenizer E5 thật, overlap 64).
- Spec (`manifests/*.json`, kiểu `DocumentSpec`): `chapters`/`sections` tuỳ chọn, `first_page`,
  `last_page`, `exclude_pages`, `join_pages`, `contextual_header`. Tài liệu PDF/MD/HTML đi qua
  `parsing.extract_text`. Mọi chunk đều phải qua `prepare`; không còn đường chunk theo ký tự.

## Nạp, duyệt, kích hoạt

```sh
../.venv/bin/python -m knowledge_ingestion.cli enqueue knowledge_ingestion/data/input/<bundle>/manifest.json
../.venv/bin/python -m knowledge_ingestion.cli worker --once      # bỏ --once để chạy liên tục
../.venv/bin/python -m knowledge_ingestion.cli verify <revision_id>
../.venv/bin/python -m knowledge_ingestion.cli review  <revision_id> --reviewer <tên>
../.venv/bin/python -m knowledge_ingestion.cli approve <revision_id> --reviewer <tên>
../.venv/bin/python -m knowledge_ingestion.cli activate
```

Worker chỉ embed chunk còn thiếu, mỗi batch commit riêng, heartbeat giữ lease, lỗi
mạng/429/5xx retry hữu hạn, vector được kiểm tra và chuẩn hoá L2. Job `FAILED`:
`retry <job_id>`. SQL chỉ đọc để kiểm tra: `sql/verify_lore_of_running.sql`.

### Chunk lại và đổi profile cùng lúc

`activate` chấp nhận khi mỗi tài liệu đang public có một revision APPROVED (bản đang active
hoặc bản mới hơn) đã `INDEXED` bằng profile đích, rồi đưa bản mới nhất lên active. Quy trình:

1. Đặt `EMBEDDING_REVISION` mới (ví dụ `e5-ctx-v2`) trong `knowledge_ingestion/.env`.
2. `prepare` → `validate` → `enqueue` → `worker` → `verify` → `review` → `approve`.
   Profile cũ vẫn phục vụ trong suốt quá trình này.
3. `activate`, rồi đặt cùng `EMBEDDING_REVISION` trong `backend/.env` và `backend/agentic/.env`
   và khởi động lại backend. Trong khoảng giữa hai bước, backend trả `503 RAG_PROFILE_NOT_READY`
   và agent dùng nguồn web.

Rollback: vector của profile cũ vẫn còn. Đặt lại revision cũ bằng SQL
(`UPDATE knowledge_revisions SET review_status='APPROVED' WHERE id=<cũ>`,
`UPDATE knowledge_documents SET active_revision=<cũ>`, đánh dấu revision mới `STALE`,
`UPDATE knowledge_profiles SET active = (id=<profile cũ>)`) rồi khôi phục `EMBEDDING_REVISION`
cũ ở backend.

## Tìm kiếm và đánh giá

Backend (`embedding/retrieval.py`): dense + full-text cho mỗi câu truy vấn, RRF, rerank
(`RERANK_ENABLED`), tối đa `RAG_MAX_PER_PAGE` đoạn mỗi trang, ngưỡng `RAG_MIN_RERANK_SCORE`
/ `RAG_MIN_DENSE_SIMILARITY`. Xem `backend/API.md`.

Đo chất lượng retrieval và hiệu chỉnh ngưỡng (bộ câu hỏi vàng, local):

```sh
../.venv/bin/python -m agentic.evaluation.rag_eval retrieval --label full --multi --rerank --options '{"thresholds": false}'
../.venv/bin/python -m agentic.evaluation.rag_eval calibrate eval_results/rag/<run>
../.venv/bin/python -m agentic.evaluation.rag_eval compare eval_results/rag/<run-a> eval_results/rag/<run-b>
```

## Docker Compose

```sh
docker compose -f backend/docker-compose.yml --profile rag up -d --build embedding-worker
docker compose -f backend/docker-compose.yml --profile rag run --rm embedding-worker \
  python -m knowledge_ingestion.cli enqueue knowledge_ingestion/data/input/<bundle>/manifest.json
```

Image dùng target `ingestion` của `backend/Dockerfile`; `data/input` và `data/.cache` được
mount read-only. Chạy `fetch-tokenizer` và `prepare` trên host trước.

## Kiểm thử

```sh
LANGSMITH_TRACING=false LANGSMITH_ENABLED=false PYTHONPATH=backend .venv/bin/python -m pytest backend/knowledge_ingestion/tests -q
LANGSMITH_TRACING=false LANGSMITH_ENABLED=false .venv/bin/python backend/knowledge_ingestion/tests/run_isolated_database.py
```

Test DB tạo một database tạm `hercfit_ingest_test_*`, chạy kiểm tra rồi xoá đúng database đó.
