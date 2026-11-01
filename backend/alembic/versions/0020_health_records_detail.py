"""Health platform M3c: richer health records and the new logs (additive only).

Existing tables keep their ids and graph capture; they gain provenance (source
record, recorded UTC offset) and detail that was dropped before:
* device_workouts: elapsed time, pauses, splits, whether a GPS route exists.
* sleep_sessions: stage segments and short awakenings (which overlap stages and
  are never summed into stage totals).
* health_samples: more sparse vitals (VO2 max, run VO2 max, sleep respiratory rate).

New records:
* ecg_recordings / irn_alerts: provider classification and device metadata; the
  ECG waveform is kept compressed, under retention, and never leaves PostgreSQL.
* workout_routes: TCX export of a workout's GPS route (location scope).
* paired_devices: what the user wears and when it last synced.
* hydration_logs, nutrition_logs: HercFit-owned or imported logs.
* symptom_logs, mood_logs, menstrual_period_logs, ovulation_test_logs: Google
  only accepts writes for these, so HercFit is the system of record.
"""
from alembic import op

revision = "0020_health_records_detail"
down_revision = "0019_health_sources"
branch_labels = depends_on = None

COMMON = """
    id uuid PRIMARY KEY,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    version_id integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,"""
LOG_SOURCE = "source varchar(20) DEFAULT 'MANUAL' NOT NULL"
SAMPLE_TYPES = ("BLOOD_GLUCOSE", "CORE_BODY_TEMPERATURE", "VO2_MAX", "RUN_VO2_MAX", "SLEEP_RESPIRATORY_RATE")


def _log_table(name: str, columns: str, *, sources: tuple[str, ...] = ("MANUAL", "AI_CONFIRMED")) -> str:
    allowed = ", ".join(f"'{source}'" for source in sources)
    return f"""
        CREATE TABLE IF NOT EXISTS {name} ({COMMON}
            {LOG_SOURCE},
            external_id varchar(300),
            timezone varchar(64) DEFAULT 'Asia/Ho_Chi_Minh' NOT NULL,
            utc_offset_s integer,
            local_date date NOT NULL,
            note text,
            {columns},
            CONSTRAINT ck_{name}_source CHECK (source IN ({allowed}))
        )"""


def upgrade():
    for table in ("daily_health_summaries", "sleep_sessions", "device_workouts", "health_samples", "body_metrics"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS source_record_id uuid "
                   f"REFERENCES health_source_records(id) ON DELETE SET NULL")
    for table in ("sleep_sessions", "device_workouts", "health_samples", "body_metrics"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS utc_offset_s integer")
    op.execute("""
        ALTER TABLE device_workouts
            ADD COLUMN IF NOT EXISTS elapsed_seconds integer,
            ADD COLUMN IF NOT EXISTS pauses jsonb DEFAULT '[]'::jsonb NOT NULL,
            ADD COLUMN IF NOT EXISTS splits jsonb DEFAULT '[]'::jsonb NOT NULL,
            ADD COLUMN IF NOT EXISTS has_route boolean DEFAULT false NOT NULL""")
    op.execute("""
        ALTER TABLE sleep_sessions
            ADD COLUMN IF NOT EXISTS stages jsonb DEFAULT '[]'::jsonb NOT NULL,
            ADD COLUMN IF NOT EXISTS short_awakenings jsonb DEFAULT '[]'::jsonb NOT NULL""")
    allowed = ", ".join(f"'{kind}'" for kind in SAMPLE_TYPES)
    op.execute("ALTER TABLE health_samples DROP CONSTRAINT IF EXISTS ck_health_samples_type")
    op.execute(f"ALTER TABLE health_samples ADD CONSTRAINT ck_health_samples_type CHECK (sample_type IN ({allowed}))")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS ecg_recordings ({COMMON}
            source varchar(20) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
            external_id varchar(300) NOT NULL,
            started_at timestamptz NOT NULL,
            ended_at timestamptz NOT NULL,
            utc_offset_s integer,
            local_date date NOT NULL,
            classification varchar(40),
            avg_hr_bpm integer,
            sampling_hz integer,
            lead_number integer,
            device_model varchar(120),
            algorithm_version varchar(60),
            waveform_zlib bytea,
            waveform_samples integer,
            retention_until date,
            source_record_id uuid REFERENCES health_source_records(id) ON DELETE SET NULL,
            CONSTRAINT uq_ecg_recordings_external UNIQUE (user_id, source, external_id),
            CONSTRAINT ck_ecg_recordings_interval CHECK (ended_at >= started_at)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ecg_recordings_user_date ON ecg_recordings (user_id, local_date)")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS irn_alerts ({COMMON}
            source varchar(20) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
            external_id varchar(300) NOT NULL,
            started_at timestamptz NOT NULL,
            ended_at timestamptz NOT NULL,
            utc_offset_s integer,
            local_date date NOT NULL,
            positive_windows integer DEFAULT 0 NOT NULL,
            windows jsonb DEFAULT '[]'::jsonb NOT NULL,
            device_model varchar(120),
            algorithm_version varchar(60),
            source_record_id uuid REFERENCES health_source_records(id) ON DELETE SET NULL,
            CONSTRAINT uq_irn_alerts_external UNIQUE (user_id, source, external_id)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS workout_routes (
            workout_id uuid PRIMARY KEY REFERENCES device_workouts(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            format varchar(10) DEFAULT 'TCX' NOT NULL,
            data_zlib bytea NOT NULL,
            sha256 char(64) NOT NULL,
            partial boolean DEFAULT false NOT NULL,
            fetched_at timestamptz DEFAULT now() NOT NULL,
            retention_until date
        )""")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS paired_devices ({COMMON}
            connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
            external_id varchar(300) NOT NULL,
            device_type varchar(20),
            device_version varchar(120),
            battery_level integer,
            battery_status varchar(40),
            features jsonb DEFAULT '[]'::jsonb NOT NULL,
            last_sync_at timestamptz,
            CONSTRAINT uq_paired_devices_external UNIQUE (connection_id, external_id)
        )""")
    op.execute(_log_table("hydration_logs", """consumed_at timestamptz NOT NULL,
            amount_ml numeric(8, 1) NOT NULL,
            user_unit varchar(30),
            CONSTRAINT ck_hydration_logs_amount CHECK (amount_ml > 0 AND amount_ml <= 10000)""",
                          sources=("MANUAL", "AI_CONFIRMED", "GOOGLE_HEALTH")))
    op.execute(_log_table("nutrition_logs", """consumed_at timestamptz NOT NULL,
            ended_at timestamptz,
            meal_type varchar(20),
            food_name varchar(255),
            meal_id uuid REFERENCES meals(id) ON DELETE SET NULL,
            food_id uuid REFERENCES foods(id) ON DELETE SET NULL,
            energy_kcal numeric(8, 1),
            protein_g numeric(8, 2),
            carbohydrate_g numeric(8, 2),
            fat_g numeric(8, 2),
            nutrients jsonb DEFAULT '{}'::jsonb NOT NULL,
            serving jsonb DEFAULT '{}'::jsonb NOT NULL""", sources=("MANUAL", "AI_CONFIRMED", "GOOGLE_HEALTH")))
    op.execute(_log_table("symptom_logs", """recorded_at timestamptz NOT NULL,
            symptoms jsonb DEFAULT '[]'::jsonb NOT NULL,
            CONSTRAINT ck_symptom_logs_symptoms CHECK (jsonb_typeof(symptoms) = 'array' AND jsonb_array_length(symptoms) > 0)"""))
    op.execute(_log_table("mood_logs", """recorded_at timestamptz NOT NULL,
            moods jsonb DEFAULT '[]'::jsonb NOT NULL,
            valences jsonb DEFAULT '[]'::jsonb NOT NULL,
            CONSTRAINT ck_mood_logs_content CHECK (jsonb_array_length(moods) + jsonb_array_length(valences) > 0)"""))
    op.execute(_log_table("menstrual_period_logs", """started_at timestamptz NOT NULL,
            ended_at timestamptz,
            CONSTRAINT ck_menstrual_period_logs_interval CHECK (ended_at IS NULL OR ended_at > started_at)"""))
    op.execute(_log_table("ovulation_test_logs", """recorded_at timestamptz NOT NULL,
            result varchar(40) NOT NULL"""))
    for table, column in (("hydration_logs", "consumed_at"), ("nutrition_logs", "consumed_at"),
                          ("symptom_logs", "recorded_at"), ("mood_logs", "recorded_at"),
                          ("menstrual_period_logs", "started_at"), ("ovulation_test_logs", "recorded_at")):
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_time ON {table} (user_id, {column})")
    for table in ("hydration_logs", "nutrition_logs"):
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_external ON {table} (user_id, source, external_id) "
                   f"WHERE external_id IS NOT NULL")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ovulation_test_logs, menstrual_period_logs, mood_logs, symptom_logs, "
               "nutrition_logs, hydration_logs, paired_devices, workout_routes, irn_alerts, ecg_recordings")
    op.execute("ALTER TABLE health_samples DROP CONSTRAINT IF EXISTS ck_health_samples_type")
    op.execute("ALTER TABLE health_samples ADD CONSTRAINT ck_health_samples_type "
               "CHECK (sample_type IN ('BLOOD_GLUCOSE', 'CORE_BODY_TEMPERATURE')) NOT VALID")
    op.execute("ALTER TABLE sleep_sessions DROP COLUMN IF EXISTS short_awakenings, DROP COLUMN IF EXISTS stages")
    op.execute("ALTER TABLE device_workouts DROP COLUMN IF EXISTS has_route, DROP COLUMN IF EXISTS splits, "
               "DROP COLUMN IF EXISTS pauses, DROP COLUMN IF EXISTS elapsed_seconds")
    for table in ("sleep_sessions", "device_workouts", "health_samples", "body_metrics"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS utc_offset_s")
    for table in ("daily_health_summaries", "sleep_sessions", "device_workouts", "health_samples", "body_metrics"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS source_record_id")
