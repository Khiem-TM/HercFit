# RAG trên tài liệu đã duyệt

Hai luồng dùng chung một lõi:

```
embedding/
  core.py      cấu hình + profile, client embedding/rerank, chuẩn hoá văn bản (dùng chung)
  ingestion/   offline, người vận hành chạy CLI: prepare → enqueue → worker → review → activate
  retrieval/   online trong backend: POST /api/knowledge/search (dense + full-text, RRF, rerank)
```

`retrieval/` chạy trong tiến trình backend (`app.py` đăng ký router); agent chỉ gọi HTTP
qua `agentic/components/hybrid_retriever.py`. Schema PostgreSQL nằm ở `alembic/`
(`0006_knowledge`, `0015_knowledge_retrieval`). `core.normalize_text` là hợp đồng giữa
`search_vector` đã lưu và câu truy vấn: đổi nó thì phải nạp lại mọi revision.

Git theo dõi code, spec trong `ingestion/manifests/` và SQL kiểm tra trong `ingestion/sql/`.
Sách nguồn, bundle đã chuẩn bị và cache tokenizer nằm trong `ingestion/data/` (bị ignore).

```
ingestion/data/
  sources/   sách/tài liệu gốc (không versioned, có bản quyền)
  input/     bundle đã prepare: cleaned.txt, chunks.jsonl, manifest.json, report.json
  .cache/    tokenizer E5 đã pin revision
```

## Chạy nhanh (từ `backend/`)

```sh
uv pip install --python ../.venv/bin/python -r agentic/embedding/ingestion/requirements.txt
export PYTHONPATH=.
../.venv/bin/python -m agentic.embedding.ingestion.cli --help
../.venv/bin/python -m agentic.embedding.ingestion.cli fetch-tokenizer
../.venv/bin/python -m agentic.embedding.ingestion.cli prepare agentic/embedding/ingestion/data/sources/<file>.txt
../.venv/bin/python -m agentic.embedding.ingestion.cli validate agentic/embedding/ingestion/data/input/lore-of-running/manifest.json
../.venv/bin/python -m agentic.embedding.ingestion.cli preflight
```

`prepare` và `validate` chạy offline (không gọi API, không mở DB). `preflight` gọi thật
embedding (query và passage) và rerank, chỉ in model, số chiều, endpoint, profile ID.
Thêm `LANGFUSE_TRACING=false` để tắt tracing cho một lệnh.

## Cấu hình

Thứ tự ưu tiên từ thấp đến cao: `backend/.env` → `backend/agentic/.env` →
`backend/agentic/embedding/ingestion/.env` → biến môi trường. Xem `ingestion/.env.example`.
`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` được ưu tiên hơn `FPT_BASE_URL`/`FPT_API_KEY`.

Profile embedding = hash(endpoint, model, `EMBEDDING_REVISION`, số chiều). Backend chỉ trả
kết quả khi profile của nó trùng profile đang active trong DB.

## Pipeline chuẩn bị (`chapter-stream-ocr-e5-v3`)

- `ingestion/cleaning.py`: Unicode NFKC, ký tự điều khiển, drop cap, từ ngắt dòng, margin lặp; giữ
  số, đơn vị, dòng bảng/danh sách. Không dùng LLM sửa nội dung.
- `ingestion/preparation.py`: các trang **liên tiếp trong cùng một chương** được nối thành một dòng văn
  bản; câu chạy qua ngắt trang được nối bằng dấu cách, từ bị gạch nối qua trang được ghép lại.
  Chunk không vượt ranh giới chương. Mỗi chunk có `page`, `page_end` (trang vật lý trong file
  nguồn) và `page_label` (trang in, tính từ `printed_page` của chương trong spec theo mục lục).
- **Contextual header**: worker embed `"<title> — <chương>\n<đoạn>"`; cột `content` giữ
  nguyên đoạn gốc nên trích dẫn và kiểm tra quote không đổi. Token của header được tính vào
  ngân sách 480 token (`ingestion/tokenization.py`, tokenizer E5 thật, overlap 64).
- Spec (`ingestion/manifests/*.json`, kiểu `DocumentSpec`): `chapters`/`sections` tuỳ chọn, `first_page`,
  `last_page`, `exclude_pages`, `join_pages`, `contextual_header`. Tài liệu PDF/MD/HTML đi qua
  `parsing.extract_text`. Mọi chunk đều phải qua `prepare`; không còn đường chunk theo ký tự.

## Nạp, duyệt, kích hoạt

```sh
../.venv/bin/python -m agentic.embedding.ingestion.cli enqueue agentic/embedding/ingestion/data/input/<bundle>/manifest.json
../.venv/bin/python -m agentic.embedding.ingestion.cli worker --once      # bỏ --once để chạy liên tục
../.venv/bin/python -m agentic.embedding.ingestion.cli verify <revision_id>
../.venv/bin/python -m agentic.embedding.ingestion.cli review  <revision_id> --reviewer <tên>
../.venv/bin/python -m agentic.embedding.ingestion.cli approve <revision_id> --reviewer <tên>
../.venv/bin/python -m agentic.embedding.ingestion.cli activate
```

Worker chỉ embed chunk còn thiếu, mỗi batch commit riêng, heartbeat giữ lease, lỗi
mạng/429/5xx retry hữu hạn, vector được kiểm tra và chuẩn hoá L2. Job `FAILED`:
`retry <job_id>`. SQL chỉ đọc để kiểm tra: `ingestion/sql/verify_lore_of_running.sql`.

### Chunk lại và đổi profile cùng lúc

`activate` chấp nhận khi mỗi tài liệu đang public có một revision APPROVED (bản đang active
hoặc bản mới hơn) đã `INDEXED` bằng profile đích, rồi đưa bản mới nhất lên active. Quy trình:

1. Đặt `EMBEDDING_REVISION` mới (ví dụ `e5-ctx-v2`) trong `agentic/embedding/ingestion/.env`.
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

Backend (`retrieval/search.py`): dense + full-text cho mỗi câu truy vấn, RRF, rerank
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
  python -m agentic.embedding.ingestion.cli enqueue agentic/embedding/ingestion/data/input/<bundle>/manifest.json
```

Image dùng target `ingestion` của `backend/Dockerfile`; `ingestion/data/input` và `ingestion/data/.cache` được
mount read-only. Chạy `fetch-tokenizer` và `prepare` trên host trước.

