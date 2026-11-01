"""Health platform M3d: two-way sync bookkeeping, analytics and assistant context.

Export (HercFit -> Google):
* google_export_settings: which export groups the user turned on (per connection).
* export_outbox: one row per business change to send, written in the business
  transaction; idempotency key, aggregate version, payload hash and a state machine
  (PENDING, DISPATCHING, SUBMITTED, VERIFYING, CONFIRMED, UNCERTAIN, CONFLICT,
  BLOCKED_PERMISSION, FAILED, SUPERSEDED).
* google_resource_mappings: which Google data point a HercFit record became, and
  whether HercFit owns it (only owned records are ever patched or deleted).
* export_conflicts: local and remote versions that diverged, until the user picks.

Analytics and context:
* health_coverage: per day and type, OBSERVED / ZERO / NO_DATA / NOT_GRANTED /
  UNSUPPORTED / NOT_SYNCED, so "no data" is never confused with "zero".
* health_baselines, derived_metrics: computed values with method and algorithm version.
* context_snapshots: precomputed assistant context per topic and period, tied to
  the consent version it was built under.
* shadow_diffs: differences found while the new pipeline runs in shadow mode.
"""
from alembic import op

revision = "0021_health_export_analytics"
down_revision = "0020_health_records_detail"
branch_labels = depends_on = None

EXPORT_STATES = ("PENDING", "DISPATCHING", "SUBMITTED", "VERIFYING", "CONFIRMED", "UNCERTAIN", "CONFLICT",
                 "BLOCKED_PERMISSION", "FAILED", "SUPERSEDED")
COVERAGE_STATES = ("OBSERVED", "ZERO", "NO_DATA", "NOT_GRANTED", "UNSUPPORTED", "NOT_SYNCED")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS google_export_settings (
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            export_group varchar(30) NOT NULL,
            enabled boolean DEFAULT false NOT NULL,
            enabled_at timestamptz,
            history_operation_id uuid REFERENCES operations(id) ON DELETE SET NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (connection_id, export_group)
        )""")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS export_outbox (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            export_group varchar(30) NOT NULL,
            aggregate_type varchar(40) NOT NULL,
            aggregate_id uuid NOT NULL,
            aggregate_version integer NOT NULL,
            op varchar(10) NOT NULL,
            data_type varchar(60) NOT NULL,
            idempotency_key varchar(120) NOT NULL,
            payload jsonb NOT NULL,
            payload_sha256 char(64) NOT NULL,
            state varchar(20) DEFAULT 'PENDING' NOT NULL,
            attempts integer DEFAULT 0 NOT NULL,
            available_at timestamptz DEFAULT now() NOT NULL,
            lease_until timestamptz,
            lease_epoch bigint DEFAULT 0 NOT NULL,
            google_operation jsonb,
            remote_name varchar(300),
            last_error varchar(120),
            operation_id uuid REFERENCES operations(id) ON DELETE SET NULL,
            created_at timestamptz DEFAULT now() NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            confirmed_at timestamptz,
            CONSTRAINT uq_export_outbox_key UNIQUE (idempotency_key),
            CONSTRAINT uq_export_outbox_version UNIQUE (aggregate_type, aggregate_id, aggregate_version, op),
            CONSTRAINT ck_export_outbox_op CHECK (op IN ('CREATE', 'UPDATE', 'DELETE')),
            CONSTRAINT ck_export_outbox_state CHECK (state IN ({_in(EXPORT_STATES)}))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_outbox_ready ON export_outbox (available_at) "
               "WHERE state IN ('PENDING', 'VERIFYING')")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_outbox_user ON export_outbox (user_id, created_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS google_resource_mappings (
            id uuid PRIMARY KEY,
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            aggregate_type varchar(40) NOT NULL,
            aggregate_id uuid NOT NULL,
            data_type varchar(60) NOT NULL,
            remote_name varchar(300),
            client_id varchar(63),
            owned_by_hercfit boolean DEFAULT true NOT NULL,
            local_version integer NOT NULL,
            payload_sha256 char(64),
            remote_sha256 char(64),
            state varchar(20) DEFAULT 'PENDING' NOT NULL,
            created_at timestamptz DEFAULT now() NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            CONSTRAINT uq_google_resource_mappings_aggregate UNIQUE (connection_id, aggregate_type, aggregate_id, data_type),
            CONSTRAINT ck_google_resource_mappings_state CHECK (state IN ('PENDING', 'CONFIRMED', 'UNCERTAIN',
                                                                          'CONFLICT', 'DELETED'))
        )""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_google_resource_mappings_remote "
               "ON google_resource_mappings (connection_id, remote_name) WHERE remote_name IS NOT NULL")
    op.execute("""
        CREATE TABLE IF NOT EXISTS export_conflicts (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            mapping_id uuid NOT NULL REFERENCES google_resource_mappings(id) ON DELETE CASCADE,
            outbox_id uuid REFERENCES export_outbox(id) ON DELETE SET NULL,
            local_payload jsonb NOT NULL,
            remote_payload jsonb,
            detected_at timestamptz DEFAULT now() NOT NULL,
            resolution varchar(20),
            resolved_at timestamptz,
            CONSTRAINT ck_export_conflicts_resolution CHECK (resolution IS NULL OR resolution IN ('KEEP_LOCAL',
                                                                                                  'ACCEPT_REMOTE'))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_export_conflicts_open ON export_conflicts (user_id) "
               "WHERE resolution IS NULL")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS health_coverage (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            data_type varchar(60) NOT NULL,
            local_date date NOT NULL,
            state varchar(20) NOT NULL,
            observed_seconds integer,
            sources jsonb DEFAULT '[]'::jsonb NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (user_id, data_type, local_date),
            CONSTRAINT ck_health_coverage_state CHECK (state IN ({_in(COVERAGE_STATES)}))
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_baselines (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            metric varchar(60) NOT NULL,
            window_days integer NOT NULL,
            as_of date NOT NULL,
            algorithm_version varchar(20) NOT NULL,
            value double precision,
            spread double precision,
            n integer NOT NULL,
            computed_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (user_id, metric, window_days, as_of, algorithm_version)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS derived_metrics (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            metric varchar(60) NOT NULL,
            period_start date NOT NULL,
            period_end date NOT NULL,
            value jsonb NOT NULL,
            method text NOT NULL,
            algorithm_version varchar(20) NOT NULL,
            inputs jsonb DEFAULT '{}'::jsonb NOT NULL,
            coverage jsonb DEFAULT '{}'::jsonb NOT NULL,
            computed_at timestamptz DEFAULT now() NOT NULL,
            CONSTRAINT uq_derived_metrics UNIQUE (user_id, metric, period_start, period_end, algorithm_version)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS context_snapshots (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            topic varchar(40) NOT NULL,
            period varchar(20) NOT NULL,
            consent_version bigint NOT NULL,
            payload jsonb NOT NULL,
            tokens integer NOT NULL,
            generated_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (user_id, topic, period)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS shadow_diffs (
            id uuid PRIMARY KEY,
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            data_type varchar(60) NOT NULL,
            window_start date NOT NULL,
            window_end date NOT NULL,
            diff_kind varchar(30) NOT NULL,
            details jsonb DEFAULT '{}'::jsonb NOT NULL,
            detected_at timestamptz DEFAULT now() NOT NULL,
            explained boolean DEFAULT false NOT NULL
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_shadow_diffs_open ON shadow_diffs (connection_id, detected_at) "
               "WHERE NOT explained")


def downgrade():
    op.execute("DROP TABLE IF EXISTS shadow_diffs, context_snapshots, derived_metrics, health_baselines, "
               "health_coverage, export_conflicts, google_resource_mappings, export_outbox, google_export_settings")
