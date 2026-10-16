# Cấu hình core

Core dùng một endpoint tương thích OpenAI, LangSmith tùy chọn, và PostgreSQL/pgvector local. Các hàm `get_model`, `get_db`, `get_db_connection`, `init_crud_db_pool`, `close_crud_db_pool` và `settings` giữ nguyên đường dẫn import.

## Model

Điền trong `backend/.env` (tham khảo `backend/.env.example`):

```dotenv
MODEL_API_KEY=your-key
MODEL_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=your-model-id
USE_FAKE_MODEL=false
```

Với OpenRouter/DeepSeek, thay endpoint và model ID bằng giá trị của nhà cung cấp. Chỉ model đã cấu hình được chấp nhận qua API, bao gồm model ID tùy chỉnh. Không còn tự dò nhiều nhà cung cấp hoặc import SDK của các nhà cung cấp khác.

Các biến cũ `OPENAI_API_KEY`/`COMPATIBLE_API_KEY`, `OPENAI_BASE_URL`/`COMPATIBLE_BASE_URL`, `MODEL_NAME`/`COMPATIBLE_MODEL` vẫn được chấp nhận. Nếu khai báo nhiều tên trong cùng nguồn cấu hình, tên mới được ưu tiên. Nên chỉ khai báo tên mới để tránh nhầm lẫn.

Không có key vẫn đọc được cấu hình và import core; `get_model()` báo lỗi khi tạo model thật. `USE_FAKE_MODEL=true` dành riêng cho kiểm thử offline, khi đó `/info` chỉ công bố model `fake`. File `.env` hiện có giữ nguyên chế độ fake; đổi thành `false` khi nhập key thật.

## LangSmith

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_PROJECT=hercfit-local
```

Key LangSmith là key dịch vụ quan sát, độc lập với key model. Để `LANGSMITH_TRACING=false` nếu chưa dùng. Tracing dùng client/callback rõ ràng cho cả API thường và AG-UI; không ghi lại key vào biến môi trường toàn cục. Các biến `LANGCHAIN_*` tương ứng vẫn được chấp nhận. `/feedback` trả 503 khi chưa cấu hình LangSmith. `/health` chỉ hiển thị trạng thái tracing được bật, không gọi mạng LangSmith mỗi lần kiểm tra sức khỏe.

## PostgreSQL và pgvector

```sh
cd backend
docker compose up -d postgres
```

Host mặc định là `localhost`; Docker Compose tự đổi thành `postgres` trong container backend. Image `pgvector/pgvector:pg16` cùng major PostgreSQL 16 với image cũ. Giữ nguyên volume hiện tại; không cần xóa dữ liệu. Script SQL chuẩn bị extension `vector` cho database mới; startup cũng chạy `CREATE EXTENSION IF NOT EXISTS vector` cho database đã có. Tài khoản local phải có quyền tạo extension.

CRUD, checkpoint và memory store đều dùng PostgreSQL. Pool CRUD được mở và kiểm tra kết nối trong lifespan, đóng khi shutdown hoặc startup lỗi; thao tác trong `get_db_connection()` commit khi thành công và rollback khi có lỗi. Khi pool chưa sẵn sàng sẽ báo lỗi thay vì trả `None`. DSN được escape bằng libpq nên mật khẩu có ký tự đặc biệt vẫn hợp lệ.

pgvector được bật mặc định. Để dùng semantic search trong LangGraph store, khai báo `EMBEDDING_MODEL` và `EMBEDDING_DIMENSIONS` đúng bằng số chiều đầu ra của model embedding. Endpoint phải hỗ trợ embeddings bằng cùng `MODEL_API_KEY`; không cần key model thứ hai. Nếu endpoint chat không hỗ trợ embeddings, để trống `EMBEDDING_MODEL`: memory key/value và checkpoint vẫn chạy trên PostgreSQL, extension vector vẫn sẵn sàng. Không tự thay kích thước vector của dữ liệu đã có; đổi model/số chiều cần kế hoạch di chuyển index riêng.

## Kiểm tra

Từ `backend`, sau khi cài `requirements.txt`:

```sh
python -m unittest discover -s tests -v
```

Các bài kiểm tra cô lập cấu hình, không đọc key thật hay gọi dịch vụ bên ngoài. Kiểm tra PostgreSQL thực tế cần Docker/PostgreSQL local đang chạy.

Phạm vi refactor này không bổ sung các agent còn thiếu trong registry và không triển khai SQL cho các service CRUD đang là stub.
