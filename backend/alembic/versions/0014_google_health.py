"""Đồng bộ Google Health API: chuỗi thời gian sức khoẻ đo được và kết nối nhà cung cấp.

* body_metrics nhận mẫu từ thiết bị: cân nặng trở thành tuỳ chọn (một dòng cân thông minh
  có thể chỉ có mỡ cơ thể), và các dòng mang source, external_id và data_source để
  đồng bộ lặp lại không bao giờ nhân đôi một số đo.
* health_connections giữ mỗi người dùng một quyền OAuth với token mã hoá Fernet;
  oauth_accounts chỉ còn dùng cho danh tính.
* daily_health_summaries, sleep_sessions, device_workouts và health_samples chứa
  những gì nhà cung cấp đo được. health_sync_runs ghi lại mọi lần đồng bộ.
* Phần ghi nhận knowledge graph có thêm DailyHealth, SleepSession và DeviceWorkout,
  chỉ phát khi người dùng cho phép trợ lý dùng dữ liệu thiết bị, và
  node User của graph có thêm giới tính và mức vận động đã khai báo.
"""
from alembic import op
from sqlalchemy import text

from core.graph_outbox import installation_statements

revision = "0014_google_health"
down_revision = "0013_food_portions"
branch_labels = None
depends_on = None

COMMON = """
    id uuid PRIMARY KEY,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    version_id integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,"""


def _range(table, field, low, high):
    return f"CONSTRAINT ck_{table}_{field} CHECK ({field} IS NULL OR ({field} >= {low} AND {field} <= {high}))"


DAILY_RANGES = {
    "steps": (0, 1_000_000), "distance_m": (0, 1_000_000), "floors": (0, 10_000),
    "active_minutes": (0, 1440), "active_zone_minutes": (0, 2880), "total_kcal": (0, 50_000),
    "active_kcal": (0, 50_000), "resting_hr_bpm": (20, 250), "hr_avg_bpm": (20, 300),
    "hr_min_bpm": (20, 300), "hr_max_bpm": (20, 300), "hrv_ms": (0, 1000), "spo2_avg_pct": (0, 100),
    "respiratory_rate": (0, 100), "vo2_max": (0, 100), "hydration_ml": (0, 100_000),
    "sleep_minutes": (0, 1440), "skin_temp_delta_c": (-20, 20),
}
SLEEP_MINUTES = ("minutes_asleep", "minutes_awake", "minutes_in_period", "minutes_to_fall_asleep",
                 "deep_minutes", "light_minutes", "rem_minutes", "awake_minutes")
WORKOUT_RANGES = {
    "active_seconds": (0, 7 * 86400), "energy_kcal": (0, 50_000), "distance_m": (0, 1_000_000),
    "steps": (0, 1_000_000), "avg_hr_bpm": (20, 300), "active_zone_minutes": (0, 2880),
    "elevation_gain_m": (-100_000, 100_000), "avg_speed_mps": (0, 1000), "run_vo2_max": (0, 100),
}

TABLES = (
    f"""CREATE TABLE IF NOT EXISTS health_connections ({COMMON}
        provider varchar(30) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
        provider_subject varchar(255) NOT NULL,
        account_email varchar(255),
        granted_scopes jsonb DEFAULT '[]'::jsonb NOT NULL,
        access_token_enc text,
        refresh_token_enc text,
        token_expires_at timestamptz,
        status varchar(20) DEFAULT 'ACTIVE' NOT NULL,
        share_with_assistant boolean DEFAULT false NOT NULL,
        consented_at timestamptz,
        timezone varchar(64),
        provider_profile jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        sync_cursor jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        last_sync_at timestamptz,
        last_success_at timestamptz,
        last_error_code varchar(64),
        next_sync_at timestamptz,
        lease_token uuid,
        lease_until timestamptz,
        CONSTRAINT uq_health_connections_user_provider UNIQUE (user_id, provider),
        CONSTRAINT ck_health_connections_status CHECK (status IN ('ACTIVE', 'NEEDS_REAUTH', 'REVOKED', 'ERROR')),
        CONSTRAINT ck_health_connections_scopes CHECK (jsonb_typeof(granted_scopes) = 'array'),
        CONSTRAINT ck_health_connections_profile CHECK (jsonb_typeof(provider_profile) = 'object'),
        CONSTRAINT ck_health_connections_cursor CHECK (jsonb_typeof(sync_cursor) = 'object')
    )""",
    "CREATE INDEX IF NOT EXISTS ix_health_connections_due ON health_connections (next_sync_at) WHERE status = 'ACTIVE'",
    f"""CREATE TABLE IF NOT EXISTS health_sync_runs ({COMMON}
        connection_id uuid NOT NULL REFERENCES health_connections(id) ON DELETE CASCADE,
        trigger varchar(12) NOT NULL,
        status varchar(12) DEFAULT 'RUNNING' NOT NULL,
        window_start date,
        window_end date,
        counts jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        error_code varchar(64),
        finished_at timestamptz,
        CONSTRAINT ck_health_sync_runs_trigger CHECK (trigger IN ('INITIAL', 'SCHEDULED', 'MANUAL')),
        CONSTRAINT ck_health_sync_runs_status CHECK (status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')),
        CONSTRAINT ck_health_sync_runs_counts CHECK (jsonb_typeof(counts) = 'object')
    )""",
    "CREATE INDEX IF NOT EXISTS ix_health_sync_runs_user_created ON health_sync_runs (user_id, created_at)",
    f"""CREATE TABLE IF NOT EXISTS daily_health_summaries ({COMMON}
        local_date date NOT NULL,
        source varchar(20) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
        timezone varchar(64) DEFAULT 'Asia/Ho_Chi_Minh' NOT NULL,
        steps integer,
        distance_m numeric(12,2),
        floors integer,
        active_minutes integer,
        active_minutes_by_level jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        active_zone_minutes integer,
        total_kcal numeric(8,1),
        active_kcal numeric(8,1),
        resting_hr_bpm integer,
        hr_avg_bpm numeric(5,1),
        hr_min_bpm integer,
        hr_max_bpm integer,
        hrv_ms numeric(6,2),
        spo2_avg_pct numeric(5,2),
        respiratory_rate numeric(5,2),
        vo2_max numeric(5,2),
        hydration_ml numeric(8,1),
        sleep_minutes integer,
        skin_temp_delta_c numeric(4,2),
        data_source jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        CONSTRAINT uq_daily_health_user_date_source UNIQUE (user_id, local_date, source),
        CONSTRAINT ck_daily_health_summaries_levels CHECK (jsonb_typeof(active_minutes_by_level) = 'object'),
        CONSTRAINT ck_daily_health_summaries_data_source CHECK (jsonb_typeof(data_source) = 'object'),
        {", ".join(_range("daily_health_summaries", f, lo, hi) for f, (lo, hi) in DAILY_RANGES.items())}
    )""",
    f"""CREATE TABLE IF NOT EXISTS sleep_sessions ({COMMON}
        source varchar(20) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
        external_id varchar(255) NOT NULL,
        start_at timestamptz NOT NULL,
        end_at timestamptz NOT NULL,
        local_date date NOT NULL,
        sleep_type varchar(20),
        is_main boolean DEFAULT false NOT NULL,
        is_nap boolean DEFAULT false NOT NULL,
        {", ".join(f + " integer" for f in SLEEP_MINUTES)},
        efficiency_pct numeric(5,2),
        data_source jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        CONSTRAINT uq_sleep_sessions_external UNIQUE (user_id, source, external_id),
        CONSTRAINT ck_sleep_sessions_interval CHECK (end_at > start_at),
        CONSTRAINT ck_sleep_sessions_data_source CHECK (jsonb_typeof(data_source) = 'object'),
        CONSTRAINT ck_sleep_sessions_efficiency_pct CHECK (efficiency_pct IS NULL OR (efficiency_pct >= 0 AND efficiency_pct <= 100)),
        {", ".join(_range("sleep_sessions", f, 0, 2880) for f in SLEEP_MINUTES)}
    )""",
    "CREATE INDEX IF NOT EXISTS ix_sleep_sessions_user_date ON sleep_sessions (user_id, local_date)",
    f"""CREATE TABLE IF NOT EXISTS device_workouts ({COMMON}
        source varchar(20) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
        external_id varchar(255) NOT NULL,
        started_at timestamptz NOT NULL,
        ended_at timestamptz NOT NULL,
        local_date date NOT NULL,
        exercise_type varchar(64),
        display_name varchar(255),
        active_seconds integer,
        energy_kcal numeric(8,1),
        distance_m numeric(12,2),
        steps integer,
        avg_hr_bpm integer,
        active_zone_minutes integer,
        hr_zone_seconds jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        elevation_gain_m numeric(10,2),
        avg_speed_mps numeric(8,3),
        run_vo2_max numeric(5,2),
        data_source jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        CONSTRAINT uq_device_workouts_external UNIQUE (user_id, source, external_id),
        CONSTRAINT ck_device_workouts_interval CHECK (ended_at >= started_at),
        CONSTRAINT ck_device_workouts_zones CHECK (jsonb_typeof(hr_zone_seconds) = 'object'),
        CONSTRAINT ck_device_workouts_data_source CHECK (jsonb_typeof(data_source) = 'object'),
        {", ".join(_range("device_workouts", f, lo, hi) for f, (lo, hi) in WORKOUT_RANGES.items())}
    )""",
    "CREATE INDEX IF NOT EXISTS ix_device_workouts_user_date ON device_workouts (user_id, local_date)",
    f"""CREATE TABLE IF NOT EXISTS health_samples ({COMMON}
        source varchar(20) DEFAULT 'GOOGLE_HEALTH' NOT NULL,
        external_id varchar(255) NOT NULL,
        sample_type varchar(30) NOT NULL,
        measured_at timestamptz NOT NULL,
        value numeric(10,3) NOT NULL,
        unit varchar(16) NOT NULL,
        details jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        data_source jsonb DEFAULT '{{}}'::jsonb NOT NULL,
        CONSTRAINT uq_health_samples_external UNIQUE (user_id, source, external_id),
        CONSTRAINT ck_health_samples_type CHECK (sample_type IN ('BLOOD_GLUCOSE', 'CORE_BODY_TEMPERATURE')),
        CONSTRAINT ck_health_samples_value CHECK (value >= 0 AND value < 10000),
        CONSTRAINT ck_health_samples_details CHECK (jsonb_typeof(details) = 'object'),
        CONSTRAINT ck_health_samples_data_source CHECK (jsonb_typeof(data_source) = 'object')
    )""",
    "CREATE INDEX IF NOT EXISTS ix_health_samples_user_measured ON health_samples (user_id, measured_at)",
)

BODY_METRICS = (
    "ALTER TABLE body_metrics ALTER COLUMN weight_kg DROP NOT NULL",
    "ALTER TABLE body_metrics ADD COLUMN IF NOT EXISTS source varchar(20) DEFAULT 'MANUAL' NOT NULL",
    "ALTER TABLE body_metrics ADD COLUMN IF NOT EXISTS external_id varchar(255)",
    "ALTER TABLE body_metrics ADD COLUMN IF NOT EXISTS data_source jsonb DEFAULT '{}'::jsonb NOT NULL",
    "ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS ck_body_metrics_any_measurement",
    "ALTER TABLE body_metrics ADD CONSTRAINT ck_body_metrics_any_measurement CHECK (weight_kg IS NOT NULL "
    "OR height_cm IS NOT NULL OR body_fat_pct IS NOT NULL OR muscle_mass_kg IS NOT NULL)",
    "ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS ck_body_metrics_source",
    "ALTER TABLE body_metrics ADD CONSTRAINT ck_body_metrics_source CHECK (source IN ('MANUAL', 'GOOGLE_HEALTH'))",
    "ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS ck_body_metrics_data_source",
    "ALTER TABLE body_metrics ADD CONSTRAINT ck_body_metrics_data_source CHECK (jsonb_typeof(data_source) = 'object')",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_body_metrics_external ON body_metrics (user_id, source, external_id) "
    "WHERE external_id IS NOT NULL AND is_active",
)


def upgrade():
    for statement in (*BODY_METRICS, *TABLES):
        op.execute(statement)
    for statement in installation_statements():
        op.execute(statement)
    # users.sex và mức vận động đã khai báo được đưa vào hồ sơ graph; phát hồ sơ một lần.
    op.execute("SELECT kg_publish_backend('User', to_jsonb(u)) FROM users u")


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT EXISTS (SELECT 1 FROM body_metrics WHERE weight_kg IS NULL)")).scalar():
        raise RuntimeError("body_metrics has device samples without weight; delete them before downgrading 0014")
    for table in ("daily_health_summaries", "sleep_sessions", "device_workouts"):
        op.execute(f"DROP TRIGGER IF EXISTS kg_capture ON {table}")
    op.execute("DROP TRIGGER IF EXISTS kg_health_consent ON health_connections")
    op.execute("DROP FUNCTION IF EXISTS kg_capture_health_consent()")
    op.execute("DROP FUNCTION IF EXISTS kg_republish_health(uuid)")
    op.execute("DROP TABLE IF EXISTS health_samples, device_workouts, sleep_sessions, daily_health_summaries, "
               "health_sync_runs, health_connections")
    op.execute("DROP INDEX IF EXISTS uq_body_metrics_external")
    for constraint in ("ck_body_metrics_data_source", "ck_body_metrics_source", "ck_body_metrics_any_measurement"):
        op.execute(f"ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS {constraint}")
    for column in ("data_source", "external_id", "source"):
        op.execute(f"ALTER TABLE body_metrics DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE body_metrics ALTER COLUMN weight_kg SET NOT NULL")
    for statement in installation_statements(health=False):
        op.execute(statement)
