"""Provenance for imported hydration and nutrition logs.

0020 created hydration_logs and nutrition_logs without source_record_id, while the
ingestion pipeline links every imported row to its health_source_records entry
(integrations/google_health/ingest/apply.py LINK_TABLES). The first real primary
import of either type failed on the missing column. Additive only.
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
