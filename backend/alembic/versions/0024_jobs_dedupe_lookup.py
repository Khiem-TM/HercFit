"""Lookup of a job by (kind, dedupe_key) in any state.

The scheduler plans periodic work once per time bucket (workers/scheduler.py
_plan_once) by checking whether a job with that key ever existed; uq_jobs_dedupe
only covers pending jobs. Additive only.
"""
from alembic import op

revision = "0024_jobs_dedupe_lookup"
down_revision = "0023_log_source_records"
branch_labels = depends_on = None


def upgrade():
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_kind_dedupe ON jobs (kind, dedupe_key) WHERE dedupe_key IS NOT NULL")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_jobs_kind_dedupe")
