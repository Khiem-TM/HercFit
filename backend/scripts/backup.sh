#!/usr/bin/env sh
# Sao lưu database HercFit bằng pg_dump (định dạng custom) ra file có ngày giờ; in đường dẫn file khi xong.
# Dùng (từ gốc repo): backend/scripts/backup.sh [thư_mục_đích]      (mặc định ./backups, đã git-ignore)
# Biến: PG_CONTAINER (mặc định hercfit-postgres), POSTGRES_USER (hercfit), POSTGRES_DB (hercfit_db).
# Bản prod: PG_CONTAINER=$(docker compose -p hercfit-prod -f backend/docker-compose.prod.yml ps -q postgres)
# Khôi phục: backend/scripts/restore.md.
set -eu

target="${1:-backups}"
container="${PG_CONTAINER:-hercfit-postgres}"
user="${POSTGRES_USER:-hercfit}"
db="${POSTGRES_DB:-hercfit_db}"

mkdir -p "$target"
file="$target/${db}_$(date +%Y%m%d_%H%M%S).dump"
# Ghi ra file tạm rồi mới đổi tên: một lần dump hỏng không để lại file trông như bản sao lưu hợp lệ.
docker exec "$container" pg_dump -U "$user" -d "$db" --format=custom > "$file.part"
mv "$file.part" "$file"
echo "$file"
