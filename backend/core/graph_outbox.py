"""Sự kiện chiếu PostgreSQL có transaction, theo danh sách cho phép, cho knowledge graph.

Việc ghi nhận được cài trong PostgreSQL để ORM, SQL hàng loạt, lời gọi API và import catalog
có cùng hợp đồng. Không thao tác mạng nào chạy trong một lệnh ghi nghiệp vụ.
Phiên bản graph độc lập với phiên bản khoá lạc quan của ORM: đổi một
món trong bữa ăn làm tăng aggregate *bữa ăn* kể cả khi phần đầu không đổi.
"""

from sqlalchemy import event


COMMON_FIELDS = ("id", "version_id", "is_active", "created_at", "updated_at")
NUTRIENT_FIELDS = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
FOOD_FIELDS = COMMON_FIELDS + (
    "owner_user_id", "source_type", "code", "name_vi", "name_en",
    "normalized_name_vi", "item_type", "category_vi", "category_en",
    "serving_size", "serving_unit",
) + NUTRIENT_FIELDS
PAYLOAD_FIELDS = {
    "User": COMMON_FIELDS,
    "Goal": COMMON_FIELDS + (
        "user_id", "title", "description", "goal_types", "weight_kg_target",
        "targets", "start_date", "target_date", "status",
    ),
    "BodyMetric": COMMON_FIELDS + (
        "user_id", "recorded_at", "weight_kg", "height_cm", "body_fat_pct",
        "muscle_mass_kg", "source",
    ),
    "Food": FOOD_FIELDS,
    "Meal": COMMON_FIELDS + (
        "user_id", "name", "consumed_at", "timezone", "source", "detail_status",
        "replaces_id", "nutrition_incomplete",
    ) + NUTRIENT_FIELDS,
    "MealItem": COMMON_FIELDS + (
        "position", "food_id", "quantity", "unit", "nutrition_incomplete",
    ) + NUTRIENT_FIELDS,
    "Training": COMMON_FIELDS + (
        "user_id", "name", "started_at", "timezone", "source", "detail_status", "discipline",
        "duration_seconds", "session_rpe", "training_load", "energy_kcal", "calories_incomplete",
        "replaces_id", "source_entry_id",
    ),
    "TrainingItem": COMMON_FIELDS + (
        "position", "exercise_id", "kind", "duration_seconds", "distance_meters",
        "volume_kg", "best_e1rm_kg", "hard_sets", "energy_kcal",
    ),
    # Chỉ định danh catalog được chiếu từ ảnh chụp bài tập.
    "ExerciseRef": ("id", "code", "name_vi", "name_en", "kind", "source_type"),
    # Dữ liệu thiết bị đeo: chỉ tổng hợp ngày và các phiên. Chỉ số sinh tồn rời (health_samples),
    # nhịp tim từng giây và thông tin xác thực nhà cung cấp không bao giờ đến graph.
    "DailyHealth": COMMON_FIELDS + (
        "user_id", "local_date", "source", "steps", "distance_m", "floors", "active_minutes",
        "active_zone_minutes", "total_kcal", "active_kcal", "resting_hr_bpm", "hr_avg_bpm", "hrv_ms",
        "spo2_avg_pct", "respiratory_rate", "vo2_max", "hydration_ml", "sleep_minutes",
    ),
    "SleepSession": COMMON_FIELDS + (
        "user_id", "source", "start_at", "end_at", "local_date", "is_main", "is_nap", "minutes_asleep",
        "minutes_awake", "minutes_in_period", "deep_minutes", "light_minutes", "rem_minutes", "efficiency_pct",
    ),
    "DeviceWorkout": COMMON_FIELDS + (
        "user_id", "source", "started_at", "ended_at", "local_date", "exercise_type", "display_name",
        "active_seconds", "energy_kcal", "distance_m", "steps", "avg_hr_bpm", "active_zone_minutes",
    ),
}
# Cá nhân hoá có cấu trúc: users.age, users.sex và mức vận động đã khai báo
# (đầu vào của phương trình năng lượng) và tập con đã qua kiểm tra TrainingProfile của
# personal_info['training']. Tên, thông tin liên lạc, chấn thương, nhịp tim tự khai và
# mọi khoá personal_info tự do khác đều không được đưa vào.
PROFILE_USER_FIELDS = ("age", "sex")
TRAINING_PROFILE_FIELDS = ("experience_level", "primary_focus", "available_days", "session_minutes", "equipment")
ACTIVITY_LEVELS = ("sedentary", "light", "moderate", "active", "very_active")
SOURCE_TABLES = {
    "User": "users", "Goal": "goals", "BodyMetric": "body_metrics",
    "Food": "foods", "Meal": "meals", "Training": "trainings",
}
CHILD_TABLES = {"MealItem": "meal_items", "TrainingItem": "training_items"}
# Dữ kiện thiết bị (DailyHealth, SleepSession, DeviceWorkout) được dựng từ bảng health_points
# bởi domains/health_records/views.publish_kg và phát qua kg_publish_backend sau mỗi lần đồng bộ;
# chúng không có bảng nguồn riêng để gắn trigger.

# Giữ phong bì này tương thích với migration database của agent. Nó cố ý
# không có FK tới users/sessions: outbox phải sống sót khi nguồn của nó bị xoá.
OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS kg_outbox (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    owner_id text,
    aggregate_version bigint NOT NULL,
    operation text NOT NULL CHECK (operation IN ('upsert', 'delete')),
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload jsonb NOT NULL,
    trace_context jsonb DEFAULT NULLIF(current_setting('hercfit.trace_context', true), '')::jsonb,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,
    last_error text,
    UNIQUE (source, aggregate_type, aggregate_id, aggregate_version, operation)
);
ALTER TABLE kg_outbox ADD COLUMN IF NOT EXISTS trace_context jsonb DEFAULT NULLIF(current_setting('hercfit.trace_context', true), '')::jsonb;
-- The agent service may have initialized the shared envelope first.
ALTER TABLE kg_outbox ALTER COLUMN event_id SET DEFAULT gen_random_uuid();
ALTER TABLE kg_outbox ALTER COLUMN occurred_at SET DEFAULT clock_timestamp();
CREATE INDEX IF NOT EXISTS ix_kg_outbox_pending
    ON kg_outbox (available_at, occurred_at) WHERE delivered_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_kg_outbox_owner ON kg_outbox (owner_id);
CREATE TABLE IF NOT EXISTS kg_source_versions (
    source text NOT NULL DEFAULT 'backend',
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    version bigint NOT NULL,
    owner_id text,
    operation text NOT NULL,
    tombstone jsonb,
    PRIMARY KEY (source, aggregate_type, aggregate_id)
);
"""


def _payload_function_sql(profile: bool = True) -> str:
    # Tên và danh sách trường là hằng số, không bao giờ là SQL từ request hay do model sinh.
    fields_by_kind = {**PAYLOAD_FIELDS, "User": PAYLOAD_FIELDS["User"] + (PROFILE_USER_FIELDS if profile else ())}
    branches = "\n".join(
        "WHEN '" + kind + "' THEN ARRAY["
        + ",".join("'" + field + "'" for field in fields) + "]::text[]"
        for kind, fields in fields_by_kind.items()
    )
    return """
CREATE OR REPLACE FUNCTION kg_allowlisted_payload(kind text, data jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb)
           || jsonb_build_object('projection_version', 1, 'schema_version', 1)
    FROM jsonb_each(data)
    WHERE key = ANY (CASE kind
    """ + branches + """
    ELSE ARRAY[]::text[] END)
$$;
"""


TRAINING_PROFILE_DDL = """
CREATE OR REPLACE FUNCTION kg_training_profile(info jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(jsonb_object_agg(key, value), '{}'::jsonb)
    FROM jsonb_each(CASE WHEN jsonb_typeof(info->'training') = 'object'
                         THEN info->'training' ELSE '{}'::jsonb END)
    WHERE key IN (""" + ", ".join("'" + field + "'" for field in TRAINING_PROFILE_FIELDS) + """)
$$;
-- The declared activity level (an energy-equation input), only when it is a known level.
CREATE OR REPLACE FUNCTION kg_activity_level(info jsonb)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN info->'activity'->>'level' IN (""" + ", ".join("'" + level + "'" for level in ACTIVITY_LEVELS) + """)
                THEN info->'activity'->>'level' END
$$;
"""
PROFILE_PAYLOAD_SQL = """
    IF kind = 'User' AND action = 'upsert' THEN
        projection := projection || jsonb_build_object('training_profile',
            kg_training_profile(data->'personal_info'), 'activity_level', kg_activity_level(data->'personal_info'));
    END IF;"""
PROFILE_GUARD_SQL = """
            AND OLD.age IS NOT DISTINCT FROM NEW.age
            AND to_jsonb(OLD)->'sex' IS NOT DISTINCT FROM to_jsonb(NEW)->'sex'
            AND kg_activity_level(OLD.personal_info) IS NOT DISTINCT FROM kg_activity_level(NEW.personal_info)
            AND kg_training_profile(OLD.personal_info)
                IS NOT DISTINCT FROM kg_training_profile(NEW.personal_info)"""

PUBLISH_DDL = """
-- Consent for the assistant to use device data: user_consents (migration 0017)
-- is the source of truth, and an active provider connection must exist. Tables
-- are resolved at run time, so earlier migrations can install this function.
CREATE OR REPLACE FUNCTION kg_device_consent(owner uuid) RETURNS boolean
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF to_regclass('health_connections') IS NULL THEN
        RETURN false;
    END IF;
    IF to_regclass('user_consents') IS NULL THEN
        RETURN EXISTS (SELECT 1 FROM health_connections c WHERE c.user_id = owner
                       AND c.share_with_assistant AND c.is_active);
    END IF;
    RETURN EXISTS (SELECT 1 FROM health_connections c WHERE c.user_id = owner AND c.is_active)
       AND EXISTS (SELECT 1 FROM user_consents u WHERE u.user_id = owner AND u.purpose = 'assistant'
                   AND u.data_group = 'device' AND u.granted);
END $$;

CREATE OR REPLACE FUNCTION kg_publish_backend(kind text, data jsonb,
                                              force_delete boolean DEFAULT false)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    entity_id text := data->>'id';
    entity_owner text;
    projection jsonb;
    next_version bigint;
    action text;
BEGIN
    IF kind NOT IN ('User', 'Goal', 'BodyMetric', 'Food', 'Meal', 'Training',
                    'DailyHealth', 'SleepSession', 'DeviceWorkout') THEN
        RAISE EXCEPTION USING MESSAGE = 'Unsupported graph aggregate: ' || kind;
    END IF;
    entity_owner := CASE kind
        WHEN 'User' THEN entity_id
        WHEN 'Food' THEN data->>'owner_user_id'
        ELSE data->>'user_id' END;
    action := CASE WHEN force_delete OR NOT COALESCE((data->>'is_active')::boolean, true)
                   OR (kind = 'Goal' AND data->>'status' <> 'IN_PROGRESS')
                   THEN 'delete' ELSE 'upsert' END;
    -- Device data reaches the assistant only with the user's consent; without it
    -- the record is published as a tombstone (kg_device_consent).
    IF action = 'upsert' AND (kind IN ('DailyHealth', 'SleepSession', 'DeviceWorkout')
            OR (kind = 'BodyMetric' AND COALESCE(data->>'source', 'MANUAL') <> 'MANUAL')) THEN
        IF NOT kg_device_consent(entity_owner::uuid) THEN
            action := 'delete';
        END IF;
    END IF;
    projection := kg_allowlisted_payload(kind, data);
    IF action = 'delete' AND (kind IN ('DailyHealth', 'SleepSession', 'DeviceWorkout')
            OR (kind = 'BodyMetric' AND COALESCE(data->>'source', 'MANUAL') <> 'MANUAL')) THEN
        -- A tombstone needs no measurements; withheld device data stays in its table.
        projection := kg_allowlisted_payload(kind, jsonb_build_object(
            'id', data->'id', 'version_id', data->'version_id', 'user_id', data->'user_id'));
    END IF;
    IF action = 'delete' THEN
        projection := projection || jsonb_build_object('is_active', false);
    END IF;
    -- Lock the per-aggregate revision before reading children. Sequence allocation
    -- and commit order are not interchangeable; this row lock serializes updates.
    INSERT INTO kg_source_versions AS versions
        (source, aggregate_type, aggregate_id, version, owner_id, operation, tombstone)
    VALUES ('backend', kind, entity_id, 1, entity_owner, action,
            CASE WHEN action = 'delete' THEN
                jsonb_build_object('id', entity_id, 'is_active', false,
                    'version_id', data->'version_id', 'projection_version', 1,
                    'schema_version', 1) ELSE NULL END)
    ON CONFLICT (source, aggregate_type, aggregate_id) DO UPDATE SET
        version = versions.version + 1, owner_id = EXCLUDED.owner_id,
        operation = EXCLUDED.operation, tombstone = EXCLUDED.tombstone
    RETURNING version INTO next_version;
    IF kind = 'Meal' AND action = 'upsert' THEN
        projection := projection || jsonb_build_object('items', COALESCE((
            SELECT jsonb_agg(
                kg_allowlisted_payload('MealItem', to_jsonb(item)) ||
                jsonb_build_object('food_snapshot',
                    kg_allowlisted_payload('Food', item.food_snapshot))
                ORDER BY item.position, item.id)
            FROM meal_items item WHERE item.meal_id = entity_id::uuid
                AND item.is_active
        ), '[]'::jsonb));
    END IF;
    IF kind = 'Training' AND action = 'upsert' THEN
        projection := projection || jsonb_build_object('items', COALESCE((
            SELECT jsonb_agg(
                kg_allowlisted_payload('TrainingItem', to_jsonb(item)) ||
                jsonb_build_object('exercise_snapshot',
                    kg_allowlisted_payload('ExerciseRef', item.exercise_snapshot))
                ORDER BY item.position, item.id)
            FROM training_items item WHERE item.training_id = entity_id::uuid
                AND item.is_active
        ), '[]'::jsonb));
    END IF;--profile-payload
    INSERT INTO kg_outbox
        (source, aggregate_type, aggregate_id, owner_id, aggregate_version,
         operation, payload)
    VALUES ('backend', kind, entity_id, entity_owner, next_version, action, projection);
END $$;

CREATE OR REPLACE FUNCTION kg_capture_backend() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    data jsonb;
    meal_row record;
    meal_ids uuid[];
    training_row record;
    training_ids uuid[];
BEGIN
    IF TG_TABLE_NAME = 'training_items' THEN
        IF TG_OP = 'INSERT' THEN
            training_ids := ARRAY[NEW.training_id];
        ELSIF TG_OP = 'DELETE' THEN
            training_ids := ARRAY[OLD.training_id];
        ELSE
            training_ids := ARRAY[OLD.training_id, NEW.training_id];
        END IF;
        FOR training_row IN SELECT * FROM trainings WHERE id = ANY(training_ids)
                            ORDER BY id FOR UPDATE LOOP
            PERFORM kg_publish_backend('Training', to_jsonb(training_row));
        END LOOP;
    ELSIF TG_TABLE_NAME = 'meal_items' THEN
        -- Child edits, FK SET NULL and cascade deletes all invalidate the meal.
        IF TG_OP = 'INSERT' THEN
            meal_ids := ARRAY[NEW.meal_id];
        ELSIF TG_OP = 'DELETE' THEN
            meal_ids := ARRAY[OLD.meal_id];
        ELSE
            meal_ids := ARRAY[OLD.meal_id, NEW.meal_id];
        END IF;
        FOR meal_row IN SELECT * FROM meals WHERE id = ANY(meal_ids)
                        ORDER BY id FOR UPDATE LOOP
            PERFORM kg_publish_backend('Meal', to_jsonb(meal_row));
        END LOOP;
    ELSE
        data := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
        -- Auth refresh and other profile edits contain no new graph fact. Never
        -- project PII, OAuth credentials or free-form personal_info keys.
        -- Nested so user-only columns (age, personal_info) are resolved for users rows only.
        IF TG_ARGV[0] = 'User' AND TG_OP = 'UPDATE' THEN
            IF OLD.is_active IS NOT DISTINCT FROM NEW.is_active--profile-guard
            THEN
                RETURN NULL;
            END IF;
        END IF;
        PERFORM kg_publish_backend(TG_ARGV[0], data, TG_OP = 'DELETE');
    END IF;
    RETURN NULL;
END $$;
"""


def _snapshot_function_sql() -> str:
    tables = SOURCE_TABLES
    scans = "\n".join(
        f"""FOR item IN SELECT * FROM {table} ORDER BY id FOR SHARE LOOP
            PERFORM kg_publish_backend('{kind}', to_jsonb(item));
            total := total + 1;
        END LOOP;"""
        for kind, table in tables.items()
    )
    return """
CREATE OR REPLACE FUNCTION kg_enqueue_snapshot() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE item record; total bigint := 0;
BEGIN
    -- Source row locks prevent a stale snapshot receiving a newer graph revision
    -- than a concurrent source mutation. The caller owns this transaction.
    """ + scans + """
    -- Rebuild also replays hard-delete tombstones. A late old event must never
    -- resurrect a deleted source after graph reconstruction.
    INSERT INTO kg_outbox
        (source, aggregate_type, aggregate_id, owner_id, aggregate_version,
         operation, payload)
    SELECT source, aggregate_type, aggregate_id, owner_id, version, 'delete', tombstone
        FROM kg_source_versions WHERE source = 'backend' AND operation = 'delete'
    ON CONFLICT (source, aggregate_type, aggregate_id, aggregate_version, operation)
    DO UPDATE SET delivered_at = NULL, attempts = 0, last_error = NULL,
                  available_at = now();
    RETURN total;
END $$;
"""


HEALTH_DDL = """
CREATE OR REPLACE FUNCTION kg_republish_health(owner uuid) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE item record; total bigint := 0;
BEGIN
    -- Consent changed. Withdrawn: every device fact the graph holds becomes a tombstone.
    -- Granted: the backend republishes current facts from health_points (views.publish_kg).
    IF NOT kg_device_consent(owner) THEN
        FOR item IN SELECT aggregate_type, aggregate_id FROM kg_source_versions
                    WHERE source = 'backend' AND owner_id = owner::text AND operation = 'upsert'
                      AND aggregate_type IN ('DailyHealth', 'SleepSession', 'DeviceWorkout') LOOP
            PERFORM kg_publish_backend(item.aggregate_type, jsonb_build_object(
                'id', item.aggregate_id, 'user_id', owner, 'version_id', 1), true);
            total := total + 1;
        END LOOP;
    END IF;
    FOR item IN SELECT * FROM body_metrics WHERE user_id = owner AND is_active AND source <> 'MANUAL'
                ORDER BY id FOR SHARE LOOP
        PERFORM kg_publish_backend('BodyMetric', to_jsonb(item)); total := total + 1;
    END LOOP;
    RETURN total;
END $$;

CREATE OR REPLACE FUNCTION kg_capture_health_consent() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- share_with_assistant is only a mirror once user_consents exists (migration 0017);
    -- consent changes then republish through kg_capture_user_consent.
    IF TG_OP = 'INSERT' OR OLD.is_active IS DISTINCT FROM NEW.is_active
       OR (to_regclass('user_consents') IS NULL
           AND OLD.share_with_assistant IS DISTINCT FROM NEW.share_with_assistant) THEN
        PERFORM kg_republish_health(NEW.user_id);
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION kg_capture_user_consent() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Granting or revoking assistant access to device data republishes it
    -- as upserts or tombstones in the same transaction.
    IF NEW.purpose = 'assistant' AND NEW.data_group = 'device'
       AND (TG_OP = 'INSERT' OR OLD.granted IS DISTINCT FROM NEW.granted) THEN
        PERFORM kg_republish_health(NEW.user_id);
    END IF;
    RETURN NULL;
END $$;
"""


def _guarded(table: str, statement: str) -> str:
    """Chỉ chạy DDL khi bảng tồn tại (các migration cũ hơn cài lại DDL hiện tại)."""
    return f"DO $guard$ BEGIN IF to_regclass('{table}') IS NOT NULL THEN {statement} END IF; END $guard$;"


def _health_trigger_statements() -> tuple[str, ...]:
    consent = _guarded("health_connections",
                       "DROP TRIGGER IF EXISTS kg_health_consent ON health_connections; "
                       "CREATE TRIGGER kg_health_consent AFTER INSERT OR UPDATE ON health_connections "
                       "FOR EACH ROW EXECUTE FUNCTION kg_capture_health_consent();")
    user_consent = _guarded("user_consents",
                            "DROP TRIGGER IF EXISTS kg_user_consent ON user_consents; "
                            "CREATE TRIGGER kg_user_consent AFTER INSERT OR UPDATE ON user_consents "
                            "FOR EACH ROW EXECUTE FUNCTION kg_capture_user_consent();")
    return consent, user_consent


def _publish_sql(profile: bool = True) -> str:
    return (PUBLISH_DDL.replace("--profile-payload", PROFILE_PAYLOAD_SQL if profile else "")
            .replace("--profile-guard", PROFILE_GUARD_SQL if profile else ""))


def installation_statements(profile: bool = True, health: bool = True) -> tuple[str, ...]:
    """DDL dùng chung cho Alembic và việc tạo metadata riêng cho test/phát triển."""
    triggers = tuple(
        f"DROP TRIGGER IF EXISTS kg_capture ON {table}; "
        f"CREATE TRIGGER kg_capture AFTER INSERT OR UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION kg_capture_backend('{kind}');"
        for kind, table in {**SOURCE_TABLES, **CHILD_TABLES}.items()
    )
    health_ddl = (HEALTH_DDL, *_health_trigger_statements()) if health else ()
    return (OUTBOX_DDL, TRAINING_PROFILE_DDL, _payload_function_sql(profile), _publish_sql(profile),
            _snapshot_function_sql(), *triggers, *health_ddl)


def install_backend_outbox(connection) -> None:
    for statement in installation_statements():
        connection.exec_driver_sql(statement)


def register_metadata_hooks(metadata) -> None:
    """Đảm bảo Base.metadata.create_all có cùng phần ghi nhận như database dựng bằng Alembic."""
    def install(_metadata, connection, **_kwargs):
        if connection.dialect.name == "postgresql":
            install_backend_outbox(connection)

    event.listen(metadata, "after_create", install)


def backend_snapshot_events(connection) -> int:
    """Xếp hàng ảnh chụp nguồn; gọi bên trong transaction PostgreSQL của bên gọi.

    Nhận một Connection đồng bộ của SQLAlchemy (AsyncConnection.run_sync cũng được).
    Worker psycopg có thể chạy trực tiếp SELECT kg_enqueue_snapshot() thay thế.
    """
    return int(connection.exec_driver_sql("SELECT kg_enqueue_snapshot()").scalar_one())
