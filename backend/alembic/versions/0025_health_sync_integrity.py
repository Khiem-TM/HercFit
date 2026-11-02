"""Stable export identity, per-type dedupe and operation/job subscriptions."""
from alembic import op

revision = "0025_health_sync_integrity"
down_revision = "0024_jobs_dedupe_lookup"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE google_resource_mappings ADD COLUMN IF NOT EXISTS confirmed_payload jsonb")
    op.execute("ALTER TABLE export_outbox ADD COLUMN IF NOT EXISTS mapping_id uuid "
               "REFERENCES google_resource_mappings(id) ON DELETE CASCADE")
    op.execute("""UPDATE export_outbox o SET mapping_id = m.id FROM google_resource_mappings m
        WHERE o.mapping_id IS NULL AND o.connection_id = m.connection_id AND o.aggregate_type = m.aggregate_type
          AND o.aggregate_id = m.aggregate_id AND o.data_type = m.data_type""")
    op.execute("""UPDATE google_resource_mappings m SET confirmed_payload = o.payload FROM export_outbox o
        WHERE o.mapping_id = m.id AND o.state = 'CONFIRMED' AND o.payload_sha256 = m.payload_sha256
          AND m.confirmed_payload IS NULL""")
    op.execute("ALTER TABLE export_outbox DROP CONSTRAINT IF EXISTS uq_export_outbox_version")
    op.execute("ALTER TABLE export_outbox ADD CONSTRAINT uq_export_outbox_version UNIQUE "
               "(connection_id, aggregate_type, aggregate_id, data_type, aggregate_version, op)")
    op.execute("CREATE INDEX ix_export_outbox_mapping_order ON export_outbox (mapping_id, created_at, id)")
    # Existing interrupted sends must be verified, never replayed as a fresh create.
    op.execute("UPDATE export_outbox SET lease_until = now() WHERE state = 'DISPATCHING' AND lease_until IS NULL")
    op.execute("""CREATE TABLE operation_jobs (
        operation_id uuid REFERENCES operations(id) ON DELETE CASCADE NOT NULL,
        job_id uuid REFERENCES jobs(id) ON DELETE CASCADE NOT NULL,
        PRIMARY KEY (operation_id, job_id))""")
    op.execute("CREATE INDEX ix_operation_jobs_job ON operation_jobs (job_id)")
    op.execute("CREATE UNIQUE INDEX uq_jobs_running_export ON jobs (connection_id) "
               "WHERE kind = 'GH_EXPORT_DISPATCH' AND state = 'RUNNING'")


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_jobs_running_export")
    op.execute("DROP TABLE IF EXISTS operation_jobs")
    op.execute("ALTER TABLE export_outbox DROP COLUMN IF EXISTS mapping_id")
    op.execute("ALTER TABLE google_resource_mappings DROP COLUMN IF EXISTS confirmed_payload")
    # Preserve per-type uniqueness: reverting to the old key would discard valid exports.
