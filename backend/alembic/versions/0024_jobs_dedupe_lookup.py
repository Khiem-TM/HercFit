"""Tra cứu job theo (kind, dedupe_key) ở mọi trạng thái.

Scheduler lập việc định kỳ một lần cho mỗi khung thời gian (workers/scheduler.py
_plan_once) bằng cách kiểm tra đã từng có job với khoá đó chưa; uq_jobs_dedupe
chỉ bao quát job đang chờ. Chỉ cộng thêm.
"""
from alembic import op

revision = "0024_jobs_dedupe_lookup"
down_revision = "0023_log_source_records"
branch_labels = depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_kind_dedupe ON jobs (kind, dedupe_key) WHERE dedupe_key IS NOT NULL")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_jobs_kind_dedupe")
