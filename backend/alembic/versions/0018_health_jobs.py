"""Health platform M3a: durable jobs, operations, webhook inbox, per-type cursors and quotas.

* jobs: PostgreSQL work queue. Claims use FOR UPDATE SKIP LOCKED and bump a
  per-job lease_epoch (fencing token); one RUNNING ingest job per (connection,
  data type); dedupe keys collapse duplicate requests while a job is pending.
* operations: what a user-visible command (Sync, export, history export)
  started; GET /api/v2/operations/{id} reports its jobs' outcome.
* webhook_inbox: every verified notification message, stored before the
  endpoint answers 204; duplicates collapse on the message hash.
* sync_cursors: per connection, data type and source family; advances only
  after a window was read completely and stored.
* rate_buckets: token buckets for Google quotas (per user and per project).
"""
from alembic import op

revision = "0018_health_jobs"
down_revision = "0017_health_identity_consent"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind varchar(40) NOT NULL,
            state varchar(20) DEFAULT 'PENDING' NOT NULL,
            result jsonb DEFAULT '{}'::jsonb NOT NULL,
            error_code varchar(64),
            created_at timestamptz DEFAULT now() NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            finished_at timestamptz,
            CONSTRAINT ck_operations_state CHECK (state IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED',
                                                             'UNCERTAIN', 'CANCELLED')),
            CONSTRAINT ck_operations_result CHECK (jsonb_typeof(result) = 'object')
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_operations_user ON operations (user_id, created_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id uuid PRIMARY KEY,
            kind varchar(40) NOT NULL,
            queue varchar(20) DEFAULT 'ingest' NOT NULL,
            dedupe_key varchar(200),
            user_id uuid REFERENCES users(id) ON DELETE CASCADE,
            connection_id uuid REFERENCES health_connections(id) ON DELETE CASCADE,
            data_type varchar(60),
            window_start date,
            window_end date,
            payload jsonb DEFAULT '{}'::jsonb NOT NULL,
            progress jsonb DEFAULT '{}'::jsonb NOT NULL,
            priority smallint DEFAULT 50 NOT NULL,
            state varchar(20) DEFAULT 'QUEUED' NOT NULL,
            attempts integer DEFAULT 0 NOT NULL,
            max_attempts integer DEFAULT 8 NOT NULL,
            run_after timestamptz DEFAULT now() NOT NULL,
            lease_owner varchar(80),
            lease_until timestamptz,
            lease_epoch bigint DEFAULT 0 NOT NULL,
            heartbeat_at timestamptz,
            connection_generation bigint,
            error_class varchar(20),
            error_code varchar(64),
            parent_id uuid REFERENCES jobs(id) ON DELETE SET NULL,
            root_id uuid,
            operation_id uuid REFERENCES operations(id) ON DELETE SET NULL,
            created_at timestamptz DEFAULT now() NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            started_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT ck_jobs_state CHECK (state IN ('QUEUED', 'RUNNING', 'RETRY', 'SUCCEEDED', 'NEEDS_ATTENTION',
                                                      'CANCELLED')),
            CONSTRAINT ck_jobs_queue CHECK (queue IN ('ingest', 'export', 'maint')),
            CONSTRAINT ck_jobs_payload CHECK (jsonb_typeof(payload) = 'object' AND jsonb_typeof(progress) = 'object'),
            CONSTRAINT ck_jobs_window CHECK (window_end IS NULL OR window_start IS NULL OR window_end >= window_start)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_ready ON jobs (queue, priority DESC, run_after) "
               "WHERE state IN ('QUEUED', 'RETRY')")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_dedupe ON jobs (kind, dedupe_key) "
               "WHERE dedupe_key IS NOT NULL AND state IN ('QUEUED', 'RETRY', 'RUNNING')")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_running_type ON jobs (connection_id, data_type) "
               "WHERE state = 'RUNNING' AND queue = 'ingest' AND data_type IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_lease ON jobs (lease_until) WHERE state = 'RUNNING'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_operation ON jobs (operation_id) WHERE operation_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_connection ON jobs (connection_id, created_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_inbox (
            id uuid PRIMARY KEY,
            received_at timestamptz DEFAULT now() NOT NULL,
            subscriber varchar(64) NOT NULL,
            health_user_id varchar(255),
            data_type varchar(60),
            operation varchar(10),
            intervals jsonb DEFAULT '[]'::jsonb NOT NULL,
            message_sha256 char(64) NOT NULL,
            message jsonb NOT NULL,
            key_id varchar(64),
            state varchar(20) DEFAULT 'RECEIVED' NOT NULL,
            job_id uuid,
            processed_at timestamptz,
            CONSTRAINT uq_webhook_inbox_message UNIQUE (message_sha256),
            CONSTRAINT ck_webhook_inbox_state CHECK (state IN ('RECEIVED', 'ROUTED', 'UNKNOWN_USER', 'IGNORED',
                                                               'FAILED'))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_inbox_pending ON webhook_inbox (received_at) "
               "WHERE state = 'RECEIVED'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_cursors (
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            data_type varchar(60) NOT NULL,
            source_family varchar(40) DEFAULT 'all-sources' NOT NULL,
            complete_through date,
            earliest_complete date,
            reverify_through date,
            status varchar(20) DEFAULT 'PENDING' NOT NULL,
            error_code varchar(64),
            schema_revision varchar(20),
            generation bigint DEFAULT 1 NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (connection_id, data_type, source_family)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_buckets (
            key varchar(120) PRIMARY KEY,
            tokens numeric(12, 3) NOT NULL,
            refilled_at timestamptz DEFAULT now() NOT NULL
        )""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS rate_buckets, sync_cursors, webhook_inbox, jobs, operations")
