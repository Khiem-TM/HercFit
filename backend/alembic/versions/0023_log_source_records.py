"""Nguồn gốc cho nhật ký nước uống và dinh dưỡng được nhập về.

0020 tạo hydration_logs và nutrition_logs mà không có source_record_id, trong khi
pipeline nhập liên kết mọi dòng nhập về với mục health_source_records của nó
(integrations/google_health/ingest/apply.py LINK_TABLES). Lần nhập primary thật đầu tiên
của hai loại này thất bại vì thiếu cột. Chỉ cộng thêm.
"""
from alembic import op

revision = "0023_log_source_records"
down_revision = "0022_api_route_usage"
branch_labels = depends_on = None

TABLES = ("hydration_logs", "nutrition_logs")


def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_record_id uuid "
                   f"REFERENCES health_source_records(id) ON DELETE SET NULL")


def downgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS source_record_id")
