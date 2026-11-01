"""Xoá token Google đã lưu, xoá dây chuyền các dòng idempotency, thêm users.sex cho mục tiêu năng lượng.

* HercFit chỉ cần danh tính Google. Access/refresh token mà các phiên bản
  trước đã ghi là thông tin xác thực ứng dụng không bao giờ dùng; chúng bị xoá.
* api_idempotency tham chiếu users mà không có ON DELETE CASCADE, điều này chặn
  quyền được xoá tài khoản của người dùng.
* users.sex (giới tính sinh học, tuỳ chọn) là đầu vào của công thức BMR Mifflin-St Jeor.
"""
from alembic import op

revision = "0012_security_profile"
down_revision = "0011_kg_profile"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE oauth_accounts SET access_token = NULL, refresh_token = NULL, token_expires_at = NULL "
               "WHERE access_token IS NOT NULL OR refresh_token IS NOT NULL OR token_expires_at IS NOT NULL")
    op.execute("ALTER TABLE api_idempotency DROP CONSTRAINT IF EXISTS api_idempotency_user_id_fkey")
    op.execute("ALTER TABLE api_idempotency ADD CONSTRAINT api_idempotency_user_id_fkey "
               "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_idempotency_created ON api_idempotency (created_at)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sex varchar(10)")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_sex")
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_sex CHECK (sex IS NULL OR sex IN ('MALE', 'FEMALE'))")


def downgrade():
    # Token nhà cung cấp đã xoá không khôi phục được; chỉ các thay đổi cấu trúc được hoàn tác.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_sex")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sex")
    op.execute("DROP INDEX IF EXISTS ix_api_idempotency_created")
    op.execute("ALTER TABLE api_idempotency DROP CONSTRAINT IF EXISTS api_idempotency_user_id_fkey")
    op.execute("ALTER TABLE api_idempotency ADD CONSTRAINT api_idempotency_user_id_fkey "
               "FOREIGN KEY (user_id) REFERENCES users(id)")
