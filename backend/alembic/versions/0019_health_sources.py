"""Health platform M3b: the source layer and compressed series.

* health_source_records: one row per provider data point (or dailyRollUp window)
  exactly as Google returned it, with its schema revision, data source, the
  three clocks (physical, civil, UTC offset) and the fetch that last saw it.
  Mark-and-sweep deletion compares `last_seen_root` with a completed fetch.
* health_series_chunks: dense samples and intervals (heart rate at 1 Hz, steps
  intervals, HRV, SpO2, ...) compressed per source and period, so 90 days for
  1,000 users stay millions of rows, not billions.
* health_record_links: which business row came from which source record.
"""
from alembic import op

revision = "0019_health_sources"
down_revision = "0018_health_jobs"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_source_records (
            id uuid PRIMARY KEY,
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            data_type varchar(60) NOT NULL,
            record_kind varchar(20) DEFAULT 'POINT' NOT NULL,
            resource_name varchar(300) NOT NULL,
            api_version varchar(8) NOT NULL,
            schema_revision varchar(20) NOT NULL,
            source_key varchar(64) NOT NULL,
            data_source jsonb DEFAULT '{}'::jsonb NOT NULL,
            payload jsonb NOT NULL,
            payload_sha256 char(64) NOT NULL,
            quality jsonb DEFAULT '{}'::jsonb NOT NULL,
            unknown_paths jsonb DEFAULT '[]'::jsonb NOT NULL,
            physical_start timestamptz,
            physical_end timestamptz,
            civil_start timestamp,
            civil_end timestamp,
            utc_offset_s integer,
            civil_date date,
            fetched_at timestamptz DEFAULT now() NOT NULL,
            last_seen_root uuid,
            deletion_state varchar(20) DEFAULT 'PRESENT' NOT NULL,
            generation bigint DEFAULT 1 NOT NULL,
            retention_until date,
            CONSTRAINT uq_health_source_records_resource UNIQUE (connection_id, data_type, resource_name),
            CONSTRAINT ck_health_source_records_kind CHECK (record_kind IN ('POINT', 'DAILY_ROLLUP', 'PROFILE')),
            CONSTRAINT ck_health_source_records_deletion CHECK (deletion_state IN ('PRESENT', 'DELETED_REMOTE',
                                                                                   'SUPERSEDED'))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_source_records_window "
               "ON health_source_records (connection_id, data_type, civil_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_source_records_user "
               "ON health_source_records (user_id, data_type, physical_start)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_source_records_retention "
               "ON health_source_records (retention_until) WHERE retention_until IS NOT NULL")
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_series_chunks (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            connection_id uuid REFERENCES health_connections(id) ON DELETE CASCADE,
            data_type varchar(60) NOT NULL,
            source_key varchar(64) NOT NULL,
            chunk_start timestamptz NOT NULL,
            chunk_end timestamptz NOT NULL,
            resolution varchar(10) NOT NULL,
            sample_count integer NOT NULL,
            encoding varchar(12) NOT NULL,
            data bytea NOT NULL,
            value_min double precision,
            value_max double precision,
            value_sum double precision,
            covered_seconds integer DEFAULT 0 NOT NULL,
            sha256 char(64) NOT NULL,
            schema_revision varchar(20) NOT NULL,
            retention_until date,
            version integer DEFAULT 1 NOT NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            CONSTRAINT uq_health_series_chunks UNIQUE (user_id, data_type, source_key, chunk_start),
            CONSTRAINT ck_health_series_chunks_span CHECK (chunk_end > chunk_start),
            CONSTRAINT ck_health_series_chunks_resolution CHECK (resolution IN ('hour', 'day')),
            CONSTRAINT ck_health_series_chunks_count CHECK (sample_count >= 0)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_series_chunks_range "
               "ON health_series_chunks (user_id, data_type, chunk_start)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS health_record_links (
            source_record_id uuid NOT NULL REFERENCES health_source_records(id) ON DELETE CASCADE,
            business_table varchar(60) NOT NULL,
            business_id uuid NOT NULL,
            link_kind varchar(20) DEFAULT 'PROJECTED' NOT NULL,
            created_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (source_record_id, business_table),
            CONSTRAINT ck_health_record_links_kind CHECK (link_kind IN ('PROJECTED', 'MERGED', 'EXPORTED'))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_health_record_links_business "
               "ON health_record_links (business_table, business_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS health_record_links, health_series_chunks, health_source_records")
