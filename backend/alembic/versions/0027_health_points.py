"""Google Health theo 5 interface: một bảng health_points, đọc bằng reconcile, đẩy gym và bữa ăn.

Thay nền tảng M3–M7 (staging, chuỗi, outbox xuất, xung đột, hàng đợi job, webhook) bằng:
* health_points: mọi dữ liệu đọc từ Google, giá trị giữ nguyên, thay thế theo cửa sổ khi đồng bộ;
* google_pushes: buổi gym / bữa ăn HercFit đã đẩy lên Google và tên các data point.

Thứ tự quan trọng:
1. Phát tombstone graph cho dữ kiện thiết bị cũ (không phụ thuộc trigger còn hay không).
2. Xoá buổi thể thao local (từ nay chỉ lấy từ Google) và số đo cơ thể đã nhập từ Google.
3. Chuyển ánh xạ đã đẩy (google_resource_mappings) để không tạo bản trùng trên Google:
   gym giữ tên điểm; bữa ăn được đánh dấu đẩy lại (một nutrition-log cho mỗi món).
4. Drop các bảng cũ, rồi cài lại DDL graph hiện tại (dữ kiện sức khoẻ được Python phát).

Không có downgrade: khôi phục bằng bản sao lưu chụp trước 0027 (dữ liệu sức khoẻ thì đồng bộ lại từ Google).
"""
from alembic import op
from core.graph_outbox import installation_statements

revision = "0027_health_points"
down_revision = "0026_health_shared_exports"
branch_labels = depends_on = None

OLD_FACTS = {"DailyHealth": "daily_health_summaries", "SleepSession": "sleep_sessions",
             "DeviceWorkout": "device_workouts"}
# Thứ tự drop: bảng tham chiếu trước bảng được tham chiếu (CASCADE vẫn được dùng cho an toàn).
DROPPED = (
    "operation_exports", "operation_jobs", "export_conflicts", "export_outbox", "google_resource_mappings",
    "google_export_settings", "shadow_diffs", "webhook_inbox", "sync_cursors", "rate_buckets", "jobs", "operations",
    "workout_routes", "health_record_links", "health_series_chunks", "ecg_recordings", "irn_alerts", "paired_devices",
    "hydration_logs", "nutrition_logs", "symptom_logs", "mood_logs", "menstrual_period_logs", "ovulation_test_logs",
    "daily_health_summaries", "sleep_sessions", "device_workouts", "health_samples", "health_coverage",
    "health_baselines", "derived_metrics", "context_snapshots", "health_sync_runs", "health_source_records",
)
GYM_GENERAL = "gym_general"


def _if_table(table: str, statement: str) -> str:
    return f"DO $guard$ BEGIN IF to_regclass('{table}') IS NOT NULL THEN {statement} END IF; END $guard$;"


def upgrade():
    # 1. Tombstone graph cho dữ kiện thiết bị cũ; DROP TABLE không kích hoạt trigger theo dòng.
    for kind, table in OLD_FACTS.items():
        op.execute(_if_table(table, f"PERFORM kg_publish_backend('{kind}', to_jsonb(t), true) FROM {table} t;"))

    # 2. Buổi thể thao local (mọi buổi có item không phải gym) và số đo cơ thể nhập từ Google.
    op.execute(f"""
        CREATE TEMP TABLE sport_trainings ON COMMIT DROP AS
        SELECT DISTINCT i.training_id AS id FROM training_items i
        WHERE i.kind::text IN ('SPORT', 'ENDURANCE')
          AND COALESCE(i.exercise_snapshot->>'code', '') <> '{GYM_GENERAL}'""")
    # replaces_id là ON DELETE RESTRICT: cắt chuỗi phiên bản trước khi xoá.
    op.execute("UPDATE trainings SET replaces_id = NULL WHERE replaces_id IN (SELECT id FROM sport_trainings)")
    op.execute("DELETE FROM trainings WHERE id IN (SELECT id FROM sport_trainings)")
    op.execute("DELETE FROM body_metrics WHERE source <> 'MANUAL'")

    # 3. Ánh xạ đã đẩy.
    op.execute("""
        CREATE TABLE health_points (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            data_type varchar(48) NOT NULL,
            kind varchar(10) NOT NULL CHECK (kind IN ('interval', 'sample', 'daily', 'session', 'food')),
            start_at timestamptz,
            end_at timestamptz,
            local_date date NOT NULL,
            value jsonb NOT NULL CHECK (jsonb_typeof(value) = 'object'),
            remote_name varchar(300) NOT NULL,
            written_by_hercfit boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_health_points_remote UNIQUE (user_id, data_type, remote_name)
        )""")
    op.execute("CREATE INDEX ix_health_points_user_type_day ON health_points (user_id, data_type, local_date)")
    op.execute("""
        CREATE TABLE google_pushes (
            record_type varchar(10) NOT NULL CHECK (record_type IN ('Training', 'Meal')),
            record_id uuid NOT NULL,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            names varchar(300)[] NOT NULL DEFAULT '{}',
            owned boolean NOT NULL DEFAULT true,
            pushed_at timestamptz,
            error varchar(120),
            PRIMARY KEY (record_type, record_id)
        )""")
    op.execute("CREATE INDEX ix_google_pushes_user_id ON google_pushes (user_id)")
    op.execute(_if_table("google_resource_mappings", """
        INSERT INTO google_pushes (record_type, record_id, user_id, names, owned, pushed_at)
        SELECT m.aggregate_type, m.aggregate_id, m.user_id, ARRAY[m.remote_name], m.owned_by_hercfit,
               CASE WHEN m.aggregate_type = 'Training' THEN now() END
        FROM google_resource_mappings m
        WHERE m.aggregate_type IN ('Training', 'Meal') AND m.remote_name IS NOT NULL AND m.state = 'CONFIRMED'
          AND (m.aggregate_type = 'Meal' OR EXISTS (SELECT 1 FROM trainings t WHERE t.id = m.aggregate_id))
        ON CONFLICT DO NOTHING;"""))

    # 4. Bảng và cột cũ.
    for table in DROPPED:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for column in ("source_record_id", "external_id", "data_source", "utc_offset_s"):
        op.execute(f"ALTER TABLE body_metrics DROP COLUMN IF EXISTS {column} CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_health_connections_due")
    op.execute("DROP INDEX IF EXISTS uq_health_connections_health_user")
    op.execute("ALTER TABLE health_connections DROP CONSTRAINT IF EXISTS ck_health_connections_api_version")
    for column in ("next_sync_at", "lease_token", "lease_until", "health_user_id", "generation", "lease_epoch",
                   "api_version"):
        op.execute(f"ALTER TABLE health_connections DROP COLUMN IF EXISTS {column}")
    # Lần đồng bộ đầu sau khi nâng cấp backfill lại từ Google.
    op.execute("UPDATE health_connections SET sync_cursor = '{}'::jsonb, last_sync_at = NULL")
    for statement in installation_statements():
        op.execute(statement)


def downgrade():
    # Khoảng 30 bảng của nền tảng cũ không được dựng lại; khôi phục bằng bản pg_dump chụp trước 0027.
    raise NotImplementedError("0027_health_points is irreversible: restore the pre-0027 database backup")
