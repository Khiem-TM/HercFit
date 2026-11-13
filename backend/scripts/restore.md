# Khôi phục database HercFit từ bản sao lưu

Bản sao lưu do `backend/scripts/backup.sh` tạo (định dạng custom của `pg_dump`, ví dụ
`backups/hercfit_db_20261113_090000.dump`). Bản sao lưu chứa dữ liệu người dùng: giữ ngoài git, không gửi qua kênh công khai.

Các lệnh dưới đây dùng container dev `hercfit-postgres`. Với bản prod, thay `docker exec hercfit-postgres` bằng
`docker compose -p hercfit-prod -f backend/docker-compose.prod.yml exec -T postgres`, và tên service tương ứng.

1. Dừng các service ghi vào database (giữ `postgres` chạy):

   ```
   docker compose -f backend/docker-compose.yml stop backend agentic kg-worker
   ```

2. Sao lưu trạng thái hiện tại trước khi ghi đè (phòng khi cần quay lại):

   ```
   backend/scripts/backup.sh backups/before-restore
   ```

3. Tạo lại database đích rỗng:

   ```
   docker exec hercfit-postgres psql -U hercfit -d postgres -c "DROP DATABASE IF EXISTS hercfit_db WITH (FORCE)"
   docker exec hercfit-postgres psql -U hercfit -d postgres -c "CREATE DATABASE hercfit_db OWNER hercfit"
   ```

4. Nạp bản sao lưu:

   ```
   docker exec -i hercfit-postgres pg_restore -U hercfit -d hercfit_db --no-owner --role=hercfit \
     < backups/hercfit_db_20261113_090000.dump
   ```

5. `pg_dump` không chứa định nghĩa role. Áp lại role tối thiểu cho agent và kg-worker (cùng mật khẩu đang dùng):

   ```
   docker exec -i hercfit-postgres psql -U hercfit -d hercfit_db -v ON_ERROR_STOP=1 \
     -v agent_password='...' -v kg_password='...' < backend/scripts/db_roles.sql
   ```

6. Khởi động lại các service (không tạo lại container phụ thuộc):

   ```
   docker compose -f backend/docker-compose.yml up -d --no-deps backend agentic kg-worker
   ```

7. Kiểm tra: đăng nhập, mở lịch sử trò chuyện và nhật ký bữa ăn, thấy dữ liệu của thời điểm sao lưu.
