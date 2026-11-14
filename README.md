# HercFit

Trợ lý AI về dinh dưỡng, tập luyện và sức khoẻ (khoá luận tốt nghiệp). Người dùng ghi bữa ăn, buổi tập, số đo bằng chat
hoặc giao diện, xem tiến độ và hỏi tư vấn có trích nguồn. Bốn trụ cột kỹ thuật: kiến trúc multi-agent với model riêng
từng agent, Knowledge Graph / Context Graph, RAG, Evaluation & Observability.

- Kiến trúc: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Dữ liệu đi đâu: [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md)
- Đánh giá: [`docs/EVALUATION.md`](docs/EVALUATION.md)
- Kịch bản demo: [`docs/DEMO.md`](docs/DEMO.md)

| Thư mục | Nội dung |
|---|---|
| `backend/` | FastAPI :8080: `core/` (auth, DB, idempotency), `domains/` (nghiệp vụ), `integrations/google_health/`, `alembic/`, `worker.py` |
| `backend/agentic/` | FastAPI :8081: LangGraph (`agents/`), `services/` (gồm `route_rules.py`), `tools/`, `knowledge_graph/`, `embedding/`, `observability/` |
| `frontend/` | Vue 3 + TypeScript + Tailwind |
| `tests/` | test đơn vị, test tích hợp, package eval `evaluation`, `Makefile` |

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

Các lệnh khác của `dev_up.sh`: `down`, `stop`, `restart`, `logs`, `status`. Sao lưu database:
`backend/scripts/backup.sh`; khôi phục: `backend/scripts/restore.md`. Bản triển khai: `backend/docker-compose.prod.yml`
(hướng dẫn ở đầu file).

## Kiểm thử

```
python3.12 -m venv .venv
.venv/bin/pip install -r tests/requirements-dev.txt -r tests/requirements-eval.txt
make -C tests check PY=$(pwd)/.venv/bin/python
```

`check` gồm lint, kiểm tra import, test đơn vị, test tích hợp, eval agent tất định, eval an toàn và an toàn Cypher.
Không gọi dịch vụ tốn phí. Test tích hợp cần Postgres đang chạy (container dev) và dùng database riêng `hercfit_test`, tự
tạo nếu chưa có; tên database phải kết thúc bằng `_test`, nếu không test dừng ngay. Máy không có `backend/.env` thì đặt
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD` qua biến môi trường.

Frontend: `cd frontend && npm test && npm run build`. Test chat chạy bằng Node/Vite,
điều khiển thứ tự các response HTTP giả; không cần trình duyệt hay dịch vụ ngoài.

Eval và thí nghiệm: [`tests/evaluation/README.md`](tests/evaluation/README.md).
