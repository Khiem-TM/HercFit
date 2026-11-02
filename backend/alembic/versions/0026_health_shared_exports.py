"""Track shared export work and retain daily aggregates for two years.

Separate from 0025 because development environments may already have applied it.
"""
from alembic import op

revision = "0026_health_shared_exports"
down_revision = "0025_health_sync_integrity"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS operation_exports (
        operation_id uuid REFERENCES operations(id) ON DELETE CASCADE NOT NULL,
        outbox_id uuid REFERENCES export_outbox(id) ON DELETE CASCADE NOT NULL,
        PRIMARY KEY (operation_id, outbox_id))""")
    op.execute("UPDATE health_source_records SET retention_until = civil_date + 730 "
               "WHERE record_kind = 'DAILY_ROLLUP' AND civil_date IS NOT NULL")


def downgrade():
    op.execute("DROP TABLE IF EXISTS operation_exports")
