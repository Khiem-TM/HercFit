# HercFit

Trợ lý AI về dinh dưỡng, tập luyện và sức khoẻ (khoá luận tốt nghiệp). Người dùng ghi bữa ăn, buổi tập, số đo bằng chat
hoặc giao diện, xem tiến độ và hỏi tư vấn có trích nguồn. Bốn trụ cột kỹ thuật: kiến trúc multi-agent với model riêng
từng agent, Knowledge Graph / Context Graph, RAG, Evaluation & Observability.

Tài liệu kiến trúc, luồng dữ liệu, đánh giá và kịch bản demo (`docs/`) cùng bộ test và eval (`tests/`,
`frontend/tests/`) chỉ giữ cục bộ, không có trong git.

| Thư mục | Nội dung |
|---|---|
| `backend/` | FastAPI :8080: `core/` (auth, DB, idempotency), `domains/` (nghiệp vụ), `integrations/google_health/`, `alembic/`, `worker.py` |
| `backend/agentic/` | FastAPI :8081: LangGraph (`agents/`), `services/` (gồm `route_rules.py`), `tools/`, `knowledge_graph/`, `embedding/`, `observability/` |
| `backend/voice/` | Worker giọng nói LiveKit (STT/TTS tiếng Việt); chỉ là lớp vào/ra của trang chat |
| `frontend/` | Vue 3 + TypeScript + Tailwind |

## Yêu cầu

- Docker Desktop (Docker Compose v2)
- Node.js 22
- Python 3.12 (CI dùng 3.12; 3.13 cũng chạy được)
- [`uv`](https://docs.astral.sh/uv/) (lệnh lint dùng `uvx ruff@0.17.4`)
- `psql` (không bắt buộc; thiếu thì test quyền database bị bỏ qua)
- Khoá dịch vụ: OAuth client Google (đăng nhập); khoá model FPT AI Marketplace. Tavily, Langfuse, Cloudinary, Google
  Health là tuỳ chọn khi phát triển.

## Chạy môi trường phát triển

1. Tạo file cấu hình từ mẫu rồi điền các giá trị bí mật (không commit file `.env`):

   ```
   cp backend/.env.example backend/.env
   cp backend/agentic/.env.example backend/agentic/.env
   ```

   | Biến | File | Ghi chú |
   |---|---|---|
   | `JWT_SECRET_KEY` | `backend/.env` | bắt buộc |
   | `AGENT_SERVICE_SECRET` | `backend/.env` | bắt buộc; agentic đọc cùng file này |
   | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | `backend/.env` | bắt buộc để đăng nhập; redirect `http://localhost:5173/auth/callback` |
   | `POSTGRES_*` | `backend/.env` | giá trị mẫu khớp container dev |
   | `MODE` | `backend/agentic/.env` | bắt buộc: `dev` hoặc `prod` |
   | `FPT_API_KEY` | `backend/agentic/.env` | bắt buộc để agent trả lời |
   | `TAVILY_API_KEY` | `backend/agentic/.env` | tra cứu web; bắt buộc khi `MODE=prod` |
   | `TOKEN_ENCRYPTION_KEY` | `backend/.env` | khi dùng Google Health |

2. Cài phụ thuộc frontend: `cd frontend && npm ci && cd ..`
3. Khởi động: `./dev_up.sh up -d`. Lệnh này chạy Postgres, backend (tự `alembic upgrade head`), agentic, Neo4j,
   kg-worker trong Docker và Vite ở `http://localhost:5173`.
4. **Lần đầu trên database mới:** agentic và kg-worker kết nối bằng role tối thiểu, nên cần tạo bảng của agent bằng role
   chủ sở hữu, rồi tạo role:

   ```
   docker compose -f backend/docker-compose.yml run --rm --no-deps \
     -e AGENT_DATABASE_URL=postgresql://hercfit:hercfit_secret@postgres:5432/hercfit_db agentic python -m agentic.scripts.migrate
   docker exec -i hercfit-postgres psql -U hercfit -d hercfit_db -v ON_ERROR_STOP=1 \
     -v agent_password=hercfit_agent_dev -v kg_password=hercfit_kg_dev < backend/scripts/db_roles.sql
   docker compose -f backend/docker-compose.yml up -d --no-deps agentic kg-worker
   ```

   Làm lại hai lệnh đầu mỗi khi có migration agent mới (`backend/agentic/migrations/`).

5. **Trò chuyện bằng giọng nói (tuỳ chọn):** tạo project trên [LiveKit Cloud](https://cloud.livekit.io), điền
   `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` vào `backend/agentic/.env`, rồi chạy `./dev_up.sh up -d --voice`
   để có thêm worker `backend/voice/worker.py`. Nút micro ở ô soạn tin bật phiên nói; LiveKit lo nhận dạng và đọc tiếng
   Việt, còn mỗi lượt nói vẫn chạy qua luồng chat như khi gõ (thẻ xác nhận duyệt được bằng câu "xác nhận" / "huỷ").
   Trong lúc agent xử lý, trợ lý nói câu đệm ("Hmm, để mình nghĩ chút nhé."); câu trả lời được Gemini Flash-Lite
   (LiveKit Inference, `VOICE_REWRITE_MODEL`) viết lại thành lời nói và `backend/voice/speech.py` kiểm tra con số, việc
   đã lưu trước khi đọc.
   Chạy worker ngoài Docker: `python -m venv backend/voice/.venv`, cài `backend/voice/requirements.txt`, rồi
   `backend/voice/.venv/bin/python backend/voice/worker.py start`.

Các lệnh khác của `dev_up.sh`: `down`, `stop`, `restart`, `logs`, `status`. Sao lưu database:
`backend/scripts/backup.sh`; khôi phục: `backend/scripts/restore.md`. Bản triển khai: `backend/docker-compose.prod.yml`
(hướng dẫn ở đầu file).

## Kiểm tra

Những bước CI chạy (`.github/workflows/quality.yml`), không gọi dịch vụ tốn phí:

```
cd backend && uvx ruff@0.17.4 check . --config agentic/ruff.toml
cd backend && MODE=dev python -c "import agentic.core.app.main, app, worker"
cd frontend && npm ci && npm run type-check && npx vite build
```
