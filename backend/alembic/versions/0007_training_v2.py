"""Training v2: derived metric columns, session load and prescription-based schedules.

Specialised Gym/Running detail stays in validated JSONB; only aggregate metrics
become columns so analytics are plain indexed SUM/MAX queries.

The meal and training schedule tables still had their pre-ORM layout
(session_name, planned_sets, target_weekly_workouts, no dates on headers), so
no schedule could be stored and Plan lifecycle queries failed. They are rebuilt
to the ORM contract; the migration refuses to run if any of them has rows.
"""

from alembic import op
from sqlalchemy import text

from core.graph_outbox import installation_statements

revision = "0007_training_v2"
down_revision = "0006_knowledge"
branch_labels = None
depends_on = None

ITEM_METRICS = ("duration_seconds", "distance_meters", "elevation_gain_meters", "volume_kg", "best_e1rm_kg", "hard_sets", "working_sets")

SCHEDULE_DDL = (
    """CREATE TABLE training_plans (
        id UUID PRIMARY KEY,
        replaces_id UUID REFERENCES training_plans (id) ON DELETE SET NULL,
        plan_id UUID NOT NULL REFERENCES plans (id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        timezone VARCHAR(100) DEFAULT 'Asia/Ho_Chi_Minh' NOT NULL,
        status VARCHAR(10) DEFAULT 'ACTIVE' NOT NULL,
        ended_at TIMESTAMP WITH TIME ZONE,
        end_reason TEXT,
        note TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        CONSTRAINT ck_training_plans_dates CHECK (end_date >= start_date),
        CONSTRAINT ck_training_plans_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_training_plans_status CHECK (status IN ('ACTIVE', 'ENDED')),
        CONSTRAINT ck_training_plans_lifecycle CHECK ((status = 'ACTIVE' AND ended_at IS NULL AND end_reason IS NULL) OR (status = 'ENDED' AND ended_at IS NOT NULL AND end_reason IS NOT NULL)),
        CONSTRAINT ck_training_plans_deleted_ended CHECK (is_active OR status = 'ENDED')
    )""",
    "CREATE UNIQUE INDEX uq_training_plans_current ON training_plans (plan_id) WHERE is_active = true AND status = 'ACTIVE'",
    "CREATE INDEX ix_training_plans_user_created ON training_plans (user_id, created_at, id)",
    """CREATE TABLE training_plan_entries (
        id UUID PRIMARY KEY,
        training_plan_id UUID NOT NULL REFERENCES training_plans (id) ON DELETE CASCADE,
        is_rest BOOLEAN DEFAULT false NOT NULL,
        scheduled_date DATE NOT NULL,
        scheduled_time TIME WITHOUT TIME ZONE,
        label VARCHAR(255) NOT NULL,
        note TEXT,
        position INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        CONSTRAINT ck_training_plan_entries_position CHECK (position >= 0),
        CONSTRAINT ck_training_plan_entries_label CHECK (label ~ '[^[:space:]]')
    )""",
    "CREATE INDEX ix_training_plan_entries_date ON training_plan_entries (training_plan_id, scheduled_date)",
    "CREATE UNIQUE INDEX uq_training_plan_entries_position ON training_plan_entries (training_plan_id, position)",
    """CREATE TABLE training_plan_items (
        id UUID PRIMARY KEY,
        entry_id UUID NOT NULL REFERENCES training_plan_entries (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        exercise_id UUID REFERENCES exercises (id) ON DELETE SET NULL,
        exercise_snapshot JSONB NOT NULL,
        prescription JSONB NOT NULL,
        note TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        CONSTRAINT ck_training_plan_items_position CHECK (position >= 0),
        CONSTRAINT ck_training_plan_items_exercise_snapshot CHECK (jsonb_typeof(exercise_snapshot) = 'object'),
        CONSTRAINT ck_training_plan_items_prescription CHECK (jsonb_typeof(prescription) = 'object')
    )""",
    "CREATE UNIQUE INDEX uq_training_plan_items_position ON training_plan_items (entry_id, position)",
)


MEAL_SCHEDULE_DDL = (
    """CREATE TABLE meal_plans (
        id UUID PRIMARY KEY,
        replaces_id UUID REFERENCES meal_plans (id) ON DELETE SET NULL,
        plan_id UUID NOT NULL REFERENCES plans (id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        timezone VARCHAR(100) DEFAULT 'Asia/Ho_Chi_Minh' NOT NULL,
        status VARCHAR(10) DEFAULT 'ACTIVE' NOT NULL,
        ended_at TIMESTAMP WITH TIME ZONE,
        end_reason TEXT,
        note TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        CONSTRAINT ck_meal_plans_dates CHECK (end_date >= start_date),
        CONSTRAINT ck_meal_plans_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_meal_plans_status CHECK (status IN ('ACTIVE', 'ENDED')),
        CONSTRAINT ck_meal_plans_lifecycle CHECK ((status = 'ACTIVE' AND ended_at IS NULL AND end_reason IS NULL) OR (status = 'ENDED' AND ended_at IS NOT NULL AND end_reason IS NOT NULL)),
        CONSTRAINT ck_meal_plans_deleted_ended CHECK (is_active OR status = 'ENDED')
    )""",
    "CREATE INDEX ix_meal_plans_user_created ON meal_plans (user_id, created_at, id)",
    "CREATE UNIQUE INDEX uq_meal_plans_current ON meal_plans (plan_id) WHERE is_active = true AND status = 'ACTIVE'",
    """CREATE TABLE meal_plan_entries (
        id UUID PRIMARY KEY,
        meal_plan_id UUID NOT NULL REFERENCES meal_plans (id) ON DELETE CASCADE,
        meal_type VARCHAR(100),
        scheduled_date DATE NOT NULL,
        scheduled_time TIME WITHOUT TIME ZONE,
        label VARCHAR(255) NOT NULL,
        note TEXT,
        position INTEGER NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        CONSTRAINT ck_meal_plan_entries_position CHECK (position >= 0),
        CONSTRAINT ck_meal_plan_entries_label CHECK (label ~ '[^[:space:]]')
    )""",
    "CREATE INDEX ix_meal_plan_entries_date ON meal_plan_entries (meal_plan_id, scheduled_date)",
    "CREATE UNIQUE INDEX uq_meal_plan_entries_position ON meal_plan_entries (meal_plan_id, position)",
    """CREATE TABLE meal_plan_items (
        id UUID PRIMARY KEY,
        entry_id UUID NOT NULL REFERENCES meal_plan_entries (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        food_id UUID REFERENCES foods (id) ON DELETE SET NULL,
        quantity NUMERIC(12, 4) NOT NULL,
        unit VARCHAR(10) NOT NULL,
        food_snapshot JSONB NOT NULL,
        nutrition_information JSONB DEFAULT '{}'::jsonb NOT NULL,
        nutrition_incomplete BOOLEAN NOT NULL,
        note TEXT,
        energy_kcal NUMERIC(18, 6),
        protein_g NUMERIC(18, 6),
        carbohydrate_g NUMERIC(18, 6),
        fat_g NUMERIC(18, 6),
        fiber_g NUMERIC(18, 6),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        CONSTRAINT ck_meal_plan_items_energy_kcal CHECK (energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)),
        CONSTRAINT ck_meal_plan_items_protein_g CHECK (protein_g IS NULL OR (protein_g >= 0 AND protein_g < 1000000000000)),
        CONSTRAINT ck_meal_plan_items_carbohydrate_g CHECK (carbohydrate_g IS NULL OR (carbohydrate_g >= 0 AND carbohydrate_g < 1000000000000)),
        CONSTRAINT ck_meal_plan_items_fat_g CHECK (fat_g IS NULL OR (fat_g >= 0 AND fat_g < 1000000000000)),
        CONSTRAINT ck_meal_plan_items_fiber_g CHECK (fiber_g IS NULL OR (fiber_g >= 0 AND fiber_g < 1000000000000)),
        CONSTRAINT ck_meal_plan_items_position CHECK (position >= 0),
        CONSTRAINT ck_meal_plan_items_quantity CHECK (quantity > 0 AND quantity < 100000000),
        CONSTRAINT ck_meal_plan_items_unit CHECK (unit IN ('G', 'ML', 'SERVING')),
        CONSTRAINT ck_meal_plan_items_snapshot CHECK (jsonb_typeof(food_snapshot) = 'object'),
        CONSTRAINT ck_meal_plan_items_nutrition CHECK (jsonb_typeof(nutrition_information) = 'object')
    )""",
    "CREATE UNIQUE INDEX uq_meal_plan_items_position ON meal_plan_items (entry_id, position)",
)


def _require_empty(*tables):
    bind = op.get_bind()
    for table in tables:
        if bind.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
            raise RuntimeError(f"{table} contains rows; migrate them explicitly before 0007")


def _rebuild_schedules():
    if _layout_current("training_plan_items", "prescription"):
        return
    _require_empty("training_plan_items", "training_plan_entries", "training_plans")
    op.execute("ALTER TABLE trainings DROP CONSTRAINT IF EXISTS trainings_source_entry_id_fkey")
    op.execute("DROP TABLE training_plan_items, training_plan_entries, training_plans")
    for statement in SCHEDULE_DDL:
        op.execute(statement)
    op.execute("""ALTER TABLE trainings ADD CONSTRAINT trainings_source_entry_id_fkey
        FOREIGN KEY (source_entry_id) REFERENCES training_plan_entries (id) ON DELETE SET NULL""")


def _layout_current(table, column):
    return op.get_bind().execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c)"
    ), {"t": table, "c": column}).scalar()


def _rebuild_meal_schedules():
    if _layout_current("meal_plans", "start_date"):
        return
    _require_empty("meal_plan_items", "meal_plan_entries", "meal_plans")
    op.execute("ALTER TABLE meals DROP CONSTRAINT IF EXISTS meals_source_entry_id_fkey")
    op.execute("DROP TABLE meal_plan_items, meal_plan_entries, meal_plans")
    for statement in MEAL_SCHEDULE_DDL:
        op.execute(statement)
    op.execute("""ALTER TABLE meals ADD CONSTRAINT meals_source_entry_id_fkey
        FOREIGN KEY (source_entry_id) REFERENCES meal_plan_entries (id) ON DELETE SET NULL""")


def upgrade():
    # Derived per-item metrics (server computed, immutable with the snapshot).
    op.execute("""ALTER TABLE training_items
        ADD COLUMN kind exercise_kind,
        ADD COLUMN duration_seconds numeric(12,3),
        ADD COLUMN distance_meters numeric(12,3),
        ADD COLUMN elevation_gain_meters numeric(10,3),
        ADD COLUMN volume_kg numeric(14,3),
        ADD COLUMN best_e1rm_kg numeric(10,3),
        ADD COLUMN hard_sets integer,
        ADD COLUMN working_sets integer""")
    for field in ITEM_METRICS:
        op.execute(f"ALTER TABLE training_items ADD CONSTRAINT ck_training_items_{field} CHECK ({field} IS NULL OR {field} >= 0)")
    op.execute("CREATE INDEX ix_training_items_exercise ON training_items (exercise_id)")

    # Session-level discipline and sRPE load.
    op.execute("""ALTER TABLE trainings
        ADD COLUMN discipline varchar(10) NOT NULL DEFAULT 'MIXED',
        ADD COLUMN session_rpe numeric(4,2),
        ADD COLUMN training_load numeric(12,3)""")
    op.execute("ALTER TABLE trainings ALTER COLUMN discipline DROP DEFAULT")
    op.execute("ALTER TABLE trainings ADD CONSTRAINT ck_trainings_discipline CHECK (discipline IN ('STRENGTH', 'ENDURANCE', 'SPORT', 'MIXED'))")
    op.execute("ALTER TABLE trainings ADD CONSTRAINT ck_trainings_session_rpe CHECK (session_rpe IS NULL OR (session_rpe >= 0 AND session_rpe <= 10))")
    op.execute("ALTER TABLE trainings ADD CONSTRAINT ck_trainings_load CHECK (training_load IS NULL OR training_load >= 0)")
    op.execute("CREATE INDEX ix_trainings_user_discipline ON trainings (user_id, discipline, started_at)")

    _rebuild_schedules()
    _rebuild_meal_schedules()

    # Endurance activity became an enum; legacy free text maps to OTHER.
    op.execute("""UPDATE exercises SET configuration = jsonb_set(configuration, '{activity}', '"OTHER"')
        WHERE kind = 'ENDURANCE' AND NOT (configuration->>'activity' = ANY (ARRAY['RUN','WALK','HIKE','CYCLE','SWIM','ROW','OTHER']))""")

    # Re-install graph capture so trainings and their items publish projections.
    for statement in installation_statements():
        op.execute(statement)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS kg_capture ON training_items")
    op.execute("DROP TRIGGER IF EXISTS kg_capture ON trainings")
    op.execute("DROP INDEX IF EXISTS ix_trainings_user_discipline")
    op.execute("""ALTER TABLE trainings DROP CONSTRAINT IF EXISTS ck_trainings_discipline,
        DROP CONSTRAINT IF EXISTS ck_trainings_session_rpe, DROP CONSTRAINT IF EXISTS ck_trainings_load,
        DROP COLUMN discipline, DROP COLUMN session_rpe, DROP COLUMN training_load""")
    op.execute("DROP INDEX IF EXISTS ix_training_items_exercise")
    op.execute("ALTER TABLE training_items " + ", ".join(f"DROP COLUMN {field}" for field in ("kind", *ITEM_METRICS)))
    # The rebuilt schedule tables match the ORM and are kept; the legacy layout
    # could not store schedules, so restoring it would only reintroduce the drift.
