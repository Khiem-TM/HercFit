"""Complete initial database schema for HercFit.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-20 09:50:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENUM_DDL = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'food_item_type') THEN
        CREATE TYPE food_item_type AS ENUM ('FOOD', 'DISH');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'food_serving_unit') THEN
        CREATE TYPE food_serving_unit AS ENUM ('G', 'ML');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'food_source_type') THEN
        CREATE TYPE food_source_type AS ENUM ('SYSTEM', 'CUSTOM');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'goal_status') THEN
        CREATE TYPE goal_status AS ENUM ('IN_PROGRESS', 'COMPLETED', 'CANCELLED');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'exercise_kind') THEN
        CREATE TYPE exercise_kind AS ENUM ('STRENGTH', 'SPORT', 'ENDURANCE');
    END IF;
END $$;
"""

TABLES = [
    # 1. users
    """
    CREATE TABLE IF NOT EXISTS users (
        id UUID NOT NULL,
        email VARCHAR(255) NOT NULL,
        fullname VARCHAR(255) NOT NULL,
        nick_name VARCHAR(100),
        avatar_url TEXT,
        email_verified BOOLEAN DEFAULT false NOT NULL,
        last_login_at TIMESTAMP WITH TIME ZONE,
        is_onboarding BOOLEAN DEFAULT false NOT NULL,
        age INTEGER,
        personal_info JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_users_personal_info_object CHECK (jsonb_typeof(personal_info) = 'object')
    );
    """,

    # 2. oauth_accounts
    """
    CREATE TABLE IF NOT EXISTS oauth_accounts (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        refresh_token TEXT,
        access_token TEXT,
        provider VARCHAR(50) DEFAULT 'google' NOT NULL,
        provider_user_id VARCHAR(255) NOT NULL,
        token_expires_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_oauth_accounts_provider_user UNIQUE (provider, provider_user_id),
        CONSTRAINT uq_oauth_accounts_user_provider UNIQUE (user_id, provider),
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 3. auth_sessions
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        refresh_token_hash VARCHAR(64) NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        revoked_at TIMESTAMP WITH TIME ZONE,
        replaced_by_session_id UUID,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_auth_sessions_replacement_not_self CHECK (replaced_by_session_id IS NULL OR replaced_by_session_id <> id),
        CONSTRAINT uq_auth_sessions_replaced_by_session_id UNIQUE (replaced_by_session_id),
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY(replaced_by_session_id) REFERENCES auth_sessions (id) ON DELETE SET NULL
    );
    """,

    # 4. body_metrics
    """
    CREATE TABLE IF NOT EXISTS body_metrics (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        recorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        weight_kg NUMERIC(10, 3) NOT NULL,
        height_cm NUMERIC(10, 3),
        body_fat_pct NUMERIC(5, 2),
        muscle_mass_kg NUMERIC(10, 3),
        additional_metrics JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_body_metrics_weight_kg CHECK (weight_kg > 0 AND weight_kg < 10000000),
        CONSTRAINT ck_body_metrics_height_cm CHECK (height_cm > 0 AND height_cm < 10000000),
        CONSTRAINT ck_body_metrics_muscle_mass_kg CHECK (muscle_mass_kg > 0 AND muscle_mass_kg < 10000000),
        CONSTRAINT ck_body_metrics_body_fat CHECK (body_fat_pct >= 0 AND body_fat_pct <= 100),
        CONSTRAINT ck_body_metrics_additional_object CHECK (jsonb_typeof(additional_metrics) = 'object'),
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 5. goals
    """
    CREATE TABLE IF NOT EXISTS goals (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        title VARCHAR(255) NOT NULL,
        description TEXT,
        goal_types JSONB DEFAULT '[]'::jsonb NOT NULL,
        weight_kg_target DOUBLE PRECISION CONSTRAINT ck_goals_weight_kg CHECK (weight_kg_target IS NULL OR (weight_kg_target > 0 AND weight_kg_target < 1000)),
        targets JSONB DEFAULT '{}'::jsonb NOT NULL,
        context JSONB DEFAULT '{}'::jsonb NOT NULL,
        start_date DATE NOT NULL,
        target_date DATE,
        status goal_status DEFAULT 'IN_PROGRESS' NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_goals_title CHECK (title ~ '[^[:space:]]'),
        CONSTRAINT ck_goals_types_array CHECK (jsonb_typeof(goal_types) = 'array'),
        CONSTRAINT ck_goals_targets_object CHECK (jsonb_typeof(targets) = 'object'),
        CONSTRAINT ck_goals_context_object CHECK (jsonb_typeof(context) = 'object'),
        CONSTRAINT ck_goals_dates CHECK (target_date IS NULL OR target_date >= start_date),
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 6. foods
    """
    CREATE TABLE IF NOT EXISTS foods (
        id UUID NOT NULL,
        code VARCHAR(128) NOT NULL,
        name_vi VARCHAR(512) NOT NULL,
        name_en VARCHAR(512),
        category_vi VARCHAR(255),
        category_en VARCHAR(255),
        item_type food_item_type DEFAULT 'FOOD' NOT NULL,
        source_type food_source_type DEFAULT 'SYSTEM' NOT NULL,
        owner_user_id UUID,
        serving_size NUMERIC(12, 4),
        serving_unit food_serving_unit DEFAULT 'G' NOT NULL,
        energy_kcal NUMERIC(18, 6),
        protein_g NUMERIC(18, 6),
        carbohydrate_g NUMERIC(18, 6),
        fat_g NUMERIC(18, 6),
        fiber_g NUMERIC(18, 6),
        nutrition_information JSONB DEFAULT '{}'::jsonb NOT NULL,
        data_quality JSONB,
        normalized_name_vi TEXT NOT NULL,
        normalized_name_en TEXT,
        normalized_search_text TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_foods_owner CHECK ((source_type = 'SYSTEM' AND owner_user_id IS NULL) OR (source_type = 'CUSTOM' AND owner_user_id IS NOT NULL)),
        CONSTRAINT ck_foods_name CHECK (name_vi ~ '[^[:space:]]'),
        CONSTRAINT ck_foods_code CHECK (code ~ '[^[:space:]]'),
        CONSTRAINT ck_foods_serving CHECK (serving_size > 0 AND serving_size < 100000000),
        CONSTRAINT ck_foods_energy_kcal CHECK (energy_kcal >= 0 AND energy_kcal < 1000000000000),
        CONSTRAINT ck_foods_protein_g CHECK (protein_g >= 0 AND protein_g < 1000000000000),
        CONSTRAINT ck_foods_carbohydrate_g CHECK (carbohydrate_g >= 0 AND carbohydrate_g < 1000000000000),
        CONSTRAINT ck_foods_fat_g CHECK (fat_g >= 0 AND fat_g < 1000000000000),
        CONSTRAINT ck_foods_fiber_g CHECK (fiber_g >= 0 AND fiber_g < 1000000000000),
        FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 7. exercises
    """
    CREATE TABLE IF NOT EXISTS exercises (
        id UUID NOT NULL,
        code VARCHAR(128) NOT NULL,
        name_vi VARCHAR(512) NOT NULL,
        name_en VARCHAR(512),
        kind exercise_kind NOT NULL,
        source_type food_source_type DEFAULT 'SYSTEM' NOT NULL,
        owner_user_id UUID,
        instructions TEXT,
        equipment JSONB DEFAULT '[]'::jsonb NOT NULL,
        muscle_groups JSONB DEFAULT '[]'::jsonb NOT NULL,
        configuration JSONB NOT NULL,
        normalized_name_vi TEXT NOT NULL,
        normalized_name_en TEXT,
        normalized_search_text TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_exercises_owner CHECK ((source_type = 'SYSTEM' AND owner_user_id IS NULL) OR (source_type = 'CUSTOM' AND owner_user_id IS NOT NULL)),
        CONSTRAINT ck_exercises_code CHECK (code ~ '[^[:space:]]'),
        CONSTRAINT ck_exercises_name CHECK (name_vi ~ '[^[:space:]]'),
        CONSTRAINT ck_exercises_equipment_array CHECK (jsonb_typeof(equipment) = 'array'),
        CONSTRAINT ck_exercises_muscle_groups_array CHECK (jsonb_typeof(muscle_groups) = 'array'),
        CONSTRAINT ck_exercises_configuration_kind CHECK (jsonb_typeof(configuration) = 'object' AND configuration ? 'kind' AND configuration->>'kind' = kind::text),
        FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 8. plans
    """
    CREATE TABLE IF NOT EXISTS plans (
        id UUID NOT NULL,
        goal_id UUID NOT NULL,
        replaces_id UUID,
        calories_in_kcal NUMERIC(12, 3),
        calories_out_kcal NUMERIC(12, 3),
        exercise_calories_kcal NUMERIC(12, 3),
        protein_g NUMERIC(12, 3),
        carbohydrate_g NUMERIC(12, 3),
        fat_g NUMERIC(12, 3),
        fiber_g NUMERIC(12, 3),
        extra_metrics JSONB DEFAULT '{}'::jsonb NOT NULL,
        source JSONB DEFAULT '{}'::jsonb NOT NULL,
        profile_snapshot JSONB NOT NULL,
        body_metric_snapshot JSONB,
        goal_snapshot JSONB NOT NULL,
        user_id UUID NOT NULL,
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
        PRIMARY KEY (id),
        CONSTRAINT ck_plans_dates CHECK (end_date >= start_date),
        CONSTRAINT ck_plans_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_plans_status CHECK (status IN ('ACTIVE', 'ENDED')),
        CONSTRAINT ck_plans_lifecycle CHECK ((status = 'ACTIVE' AND ended_at IS NULL AND end_reason IS NULL) OR (status = 'ENDED' AND ended_at IS NOT NULL AND end_reason IS NOT NULL)),
        CONSTRAINT ck_plans_deleted_ended CHECK (is_active OR status = 'ENDED'),
        CONSTRAINT ck_plans_calories_in_kcal CHECK (calories_in_kcal >= 0 AND calories_in_kcal < 1000000000),
        CONSTRAINT ck_plans_calories_out_kcal CHECK (calories_out_kcal >= 0 AND calories_out_kcal < 1000000000),
        CONSTRAINT ck_plans_exercise_calories_kcal CHECK (exercise_calories_kcal >= 0 AND exercise_calories_kcal < 1000000000),
        CONSTRAINT ck_plans_protein_g CHECK (protein_g >= 0 AND protein_g < 1000000000),
        CONSTRAINT ck_plans_carbohydrate_g CHECK (carbohydrate_g >= 0 AND carbohydrate_g < 1000000000),
        CONSTRAINT ck_plans_fat_g CHECK (fat_g >= 0 AND fat_g < 1000000000),
        CONSTRAINT ck_plans_fiber_g CHECK (fiber_g >= 0 AND fiber_g < 1000000000),
        FOREIGN KEY(goal_id) REFERENCES goals (id),
        FOREIGN KEY(replaces_id) REFERENCES plans (id) ON DELETE SET NULL,
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 9. meal_plans
    """
    CREATE TABLE IF NOT EXISTS meal_plans (
        id UUID NOT NULL,
        plan_id UUID NOT NULL,
        user_id UUID NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        target_calories_kcal NUMERIC(12, 3),
        target_protein_g NUMERIC(12, 3),
        target_carbs_g NUMERIC(12, 3),
        target_fat_g NUMERIC(12, 3),
        status VARCHAR(10) DEFAULT 'ACTIVE' NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_meal_plans_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_meal_plans_status CHECK (status IN ('ACTIVE', 'ENDED')),
        FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 10. training_plans
    """
    CREATE TABLE IF NOT EXISTS training_plans (
        id UUID NOT NULL,
        plan_id UUID NOT NULL,
        user_id UUID NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        target_weekly_workouts INTEGER,
        status VARCHAR(10) DEFAULT 'ACTIVE' NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_training_plans_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_training_plans_status CHECK (status IN ('ACTIVE', 'ENDED')),
        FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
    );
    """,

    # 11. meal_plan_entries
    """
    CREATE TABLE IF NOT EXISTS meal_plan_entries (
        id UUID NOT NULL,
        meal_plan_id UUID NOT NULL,
        position INTEGER NOT NULL,
        scheduled_date DATE NOT NULL,
        meal_type VARCHAR(50) NOT NULL,
        notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_meal_plan_entries_position CHECK (position >= 0),
        CONSTRAINT ck_meal_plan_entries_meal_type CHECK (meal_type IN ('BREAKFAST', 'LUNCH', 'DINNER', 'SNACK', 'PRE_WORKOUT', 'POST_WORKOUT')),
        CONSTRAINT uq_meal_plan_entries_position UNIQUE (meal_plan_id, position),
        FOREIGN KEY(meal_plan_id) REFERENCES meal_plans (id) ON DELETE CASCADE
    );
    """,

    # 12. training_plan_entries
    """
    CREATE TABLE IF NOT EXISTS training_plan_entries (
        id UUID NOT NULL,
        training_plan_id UUID NOT NULL,
        position INTEGER NOT NULL,
        scheduled_date DATE NOT NULL,
        session_name VARCHAR(255) NOT NULL,
        notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_training_plan_entries_position CHECK (position >= 0),
        CONSTRAINT ck_training_plan_entries_name CHECK (session_name ~ '[^[:space:]]'),
        CONSTRAINT uq_training_plan_entries_position UNIQUE (training_plan_id, position),
        FOREIGN KEY(training_plan_id) REFERENCES training_plans (id) ON DELETE CASCADE
    );
    """,

    # 13. meal_plan_items
    """
    CREATE TABLE IF NOT EXISTS meal_plan_items (
        id UUID NOT NULL,
        entry_id UUID NOT NULL,
        position INTEGER NOT NULL,
        food_id UUID,
        food_snapshot JSONB NOT NULL,
        quantity NUMERIC(12, 4) NOT NULL,
        unit VARCHAR(50) NOT NULL,
        energy_kcal NUMERIC(18, 6),
        protein_g NUMERIC(18, 6),
        carbohydrate_g NUMERIC(18, 6),
        fat_g NUMERIC(18, 6),
        fiber_g NUMERIC(18, 6),
        notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_meal_plan_items_position CHECK (position >= 0),
        CONSTRAINT ck_meal_plan_items_quantity CHECK (quantity > 0 AND quantity < 100000000),
        CONSTRAINT ck_meal_plan_items_unit CHECK (unit IN ('G', 'ML', 'SERVING')),
        CONSTRAINT ck_meal_plan_items_snapshot CHECK (jsonb_typeof(food_snapshot) = 'object'),
        CONSTRAINT uq_meal_plan_items_position UNIQUE (entry_id, position),
        FOREIGN KEY(entry_id) REFERENCES meal_plan_entries (id) ON DELETE CASCADE,
        FOREIGN KEY(food_id) REFERENCES foods (id) ON DELETE SET NULL
    );
    """,

    # 14. training_plan_items
    """
    CREATE TABLE IF NOT EXISTS training_plan_items (
        id UUID NOT NULL,
        entry_id UUID NOT NULL,
        position INTEGER NOT NULL,
        exercise_id UUID,
        exercise_snapshot JSONB NOT NULL,
        planned_sets JSONB NOT NULL,
        notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_training_plan_items_position CHECK (position >= 0),
        CONSTRAINT ck_training_plan_items_exercise_snapshot CHECK (jsonb_typeof(exercise_snapshot) = 'object'),
        CONSTRAINT ck_training_plan_items_planned_sets CHECK (jsonb_typeof(planned_sets) = 'array'),
        CONSTRAINT uq_training_plan_items_position UNIQUE (entry_id, position),
        FOREIGN KEY(entry_id) REFERENCES training_plan_entries (id) ON DELETE CASCADE,
        FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE SET NULL
    );
    """,

    # 15. meals
    """
    CREATE TABLE IF NOT EXISTS meals (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        plan_id UUID,
        name VARCHAR(255) NOT NULL,
        consumed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        meal_type VARCHAR(50) NOT NULL,
        energy_kcal NUMERIC(18, 6),
        protein_g NUMERIC(18, 6),
        carbohydrate_g NUMERIC(18, 6),
        fat_g NUMERIC(18, 6),
        fiber_g NUMERIC(18, 6),
        notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_meals_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_meals_meal_type CHECK (meal_type IN ('BREAKFAST', 'LUNCH', 'DINNER', 'SNACK', 'PRE_WORKOUT', 'POST_WORKOUT')),
        CONSTRAINT ck_meals_energy_kcal CHECK (energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)),
        CONSTRAINT ck_meals_protein_g CHECK (protein_g IS NULL OR (protein_g >= 0 AND protein_g < 1000000000000)),
        CONSTRAINT ck_meals_carbohydrate_g CHECK (carbohydrate_g IS NULL OR (carbohydrate_g >= 0 AND carbohydrate_g < 1000000000000)),
        CONSTRAINT ck_meals_fat_g CHECK (fat_g IS NULL OR (fat_g >= 0 AND fat_g < 1000000000000)),
        CONSTRAINT ck_meals_fiber_g CHECK (fiber_g IS NULL OR (fiber_g >= 0 AND fiber_g < 1000000000000)),
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE SET NULL
    );
    """,

    # 16. meal_items
    """
    CREATE TABLE IF NOT EXISTS meal_items (
        id UUID NOT NULL,
        meal_id UUID NOT NULL,
        position INTEGER NOT NULL,
        food_id UUID,
        food_snapshot JSONB NOT NULL,
        quantity NUMERIC(12, 4) NOT NULL,
        unit VARCHAR(50) NOT NULL,
        energy_kcal NUMERIC(18, 6),
        protein_g NUMERIC(18, 6),
        carbohydrate_g NUMERIC(18, 6),
        fat_g NUMERIC(18, 6),
        fiber_g NUMERIC(18, 6),
        nutrition_information JSONB DEFAULT '{}'::jsonb NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_meal_items_position CHECK (position >= 0),
        CONSTRAINT ck_meal_items_quantity CHECK (quantity > 0 AND quantity < 100000000),
        CONSTRAINT ck_meal_items_unit CHECK (unit IN ('G', 'ML', 'SERVING')),
        CONSTRAINT ck_meal_items_snapshot CHECK (jsonb_typeof(food_snapshot) = 'object'),
        CONSTRAINT ck_meal_items_nutrition CHECK (jsonb_typeof(nutrition_information) = 'object'),
        CONSTRAINT ck_meal_items_energy_kcal CHECK (energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)),
        CONSTRAINT ck_meal_items_protein_g CHECK (protein_g IS NULL OR (protein_g >= 0 AND protein_g < 1000000000000)),
        CONSTRAINT ck_meal_items_carbohydrate_g CHECK (carbohydrate_g IS NULL OR (carbohydrate_g >= 0 AND carbohydrate_g < 1000000000000)),
        CONSTRAINT ck_meal_items_fat_g CHECK (fat_g IS NULL OR (fat_g >= 0 AND fat_g < 1000000000000)),
        CONSTRAINT ck_meal_items_fiber_g CHECK (fiber_g IS NULL OR (fiber_g >= 0 AND fiber_g < 1000000000000)),
        CONSTRAINT uq_meal_items_position UNIQUE (meal_id, position),
        FOREIGN KEY(meal_id) REFERENCES meals (id) ON DELETE CASCADE,
        FOREIGN KEY(food_id) REFERENCES foods (id) ON DELETE SET NULL
    );
    """,

    # 17. trainings
    """
    CREATE TABLE IF NOT EXISTS trainings (
        id UUID NOT NULL,
        user_id UUID NOT NULL,
        plan_id UUID,
        name VARCHAR(255) NOT NULL,
        started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        ended_at TIMESTAMP WITH TIME ZONE,
        duration_minutes INTEGER,
        total_calories_burned NUMERIC(12, 3),
        notes TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_trainings_name CHECK (name ~ '[^[:space:]]'),
        CONSTRAINT ck_trainings_duration CHECK (duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 1440)),
        CONSTRAINT ck_trainings_calories CHECK (total_calories_burned IS NULL OR (total_calories_burned >= 0 AND total_calories_burned < 1000000)),
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE SET NULL
    );
    """,

    # 18. training_items
    """
    CREATE TABLE IF NOT EXISTS training_items (
        id UUID NOT NULL,
        training_id UUID NOT NULL,
        position INTEGER NOT NULL,
        exercise_id UUID,
        exercise_snapshot JSONB NOT NULL,
        performance JSONB NOT NULL,
        calorie_estimate JSONB NOT NULL,
        energy_kcal NUMERIC(18, 6),
        note TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        version_id INTEGER DEFAULT 1 NOT NULL,
        is_active BOOLEAN DEFAULT true NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_training_items_position CHECK (position >= 0),
        CONSTRAINT ck_training_items_exercise_snapshot CHECK (jsonb_typeof(exercise_snapshot) = 'object'),
        CONSTRAINT ck_training_items_performance CHECK (jsonb_typeof(performance) = 'object'),
        CONSTRAINT ck_training_items_calorie_estimate CHECK (jsonb_typeof(calorie_estimate) = 'object'),
        CONSTRAINT ck_training_items_energy CHECK (energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)),
        CONSTRAINT uq_training_items_position UNIQUE (training_id, position),
        FOREIGN KEY(training_id) REFERENCES trainings (id) ON DELETE CASCADE,
        FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE SET NULL
    );
    """
]

INDEXES = [
    # users
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_ci ON users (lower(email));",

    # auth_sessions
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_auth_sessions_refresh_token_hash ON auth_sessions (refresh_token_hash);",
    "CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_id ON auth_sessions (user_id);",

    # body_metrics
    "CREATE INDEX IF NOT EXISTS ix_body_metrics_user_recorded ON body_metrics (user_id, recorded_at, id);",

    # goals
    "CREATE INDEX IF NOT EXISTS ix_goals_user_created ON goals (user_id, created_at, id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_goals_current_user ON goals (user_id) WHERE is_active = true AND status = 'IN_PROGRESS';",

    # foods
    "CREATE INDEX IF NOT EXISTS ix_foods_browse ON foods (normalized_name_vi, id);",
    "CREATE INDEX IF NOT EXISTS ix_foods_owner_user_id ON foods (owner_user_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_foods_system_code ON foods (item_type, code) WHERE source_type = 'SYSTEM';",

    # exercises
    "CREATE INDEX IF NOT EXISTS ix_exercises_browse ON exercises (normalized_name_vi, id);",
    "CREATE INDEX IF NOT EXISTS ix_exercises_owner_user_id ON exercises (owner_user_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_exercises_system_code ON exercises (kind, code) WHERE source_type = 'SYSTEM';",

    # plans
    "CREATE INDEX IF NOT EXISTS ix_plans_goal ON plans (goal_id);",
    "CREATE INDEX IF NOT EXISTS ix_plans_user_created ON plans (user_id, created_at, id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_plans_current ON plans (user_id) WHERE is_active = true AND status = 'ACTIVE';",

    # meal_plans
    "CREATE INDEX IF NOT EXISTS ix_meal_plans_user_created ON meal_plans (user_id, created_at, id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_meal_plans_current ON meal_plans (plan_id) WHERE is_active = true AND status = 'ACTIVE';",

    # training_plans
    "CREATE INDEX IF NOT EXISTS ix_training_plans_user_created ON training_plans (user_id, created_at, id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_plans_current ON training_plans (plan_id) WHERE is_active = true AND status = 'ACTIVE';",

    # meal_plan_entries & training_plan_entries
    "CREATE INDEX IF NOT EXISTS ix_meal_plan_entries_date ON meal_plan_entries (meal_plan_id, scheduled_date);",
    "CREATE INDEX IF NOT EXISTS ix_training_plan_entries_date ON training_plan_entries (training_plan_id, scheduled_date);",

    # meals & trainings
    "CREATE INDEX IF NOT EXISTS ix_meals_user_consumed ON meals (user_id, consumed_at, id);",
    "CREATE INDEX IF NOT EXISTS ix_trainings_user_started ON trainings (user_id, started_at, id);"
]

DOWN_TABLE_ORDER = [
    "training_items",
    "meal_items",
    "trainings",
    "meals",
    "training_plan_items",
    "meal_plan_items",
    "training_plan_entries",
    "meal_plan_entries",
    "training_plans",
    "meal_plans",
    "plans",
    "exercises",
    "foods",
    "goals",
    "body_metrics",
    "auth_sessions",
    "oauth_accounts",
    "users",
]

DOWN_ENUMS = [
    "exercise_kind",
    "goal_status",
    "food_source_type",
    "food_serving_unit",
    "food_item_type",
]


def upgrade() -> None:
    # 1. Enums
    op.execute(ENUM_DDL)

    # 2. Tables
    for table_sql in TABLES:
        op.execute(table_sql)

    # 3. Indexes
    for index_sql in INDEXES:
        op.execute(index_sql)


def downgrade() -> None:
    # 1. Drop tables in reverse dependency order
    for table in DOWN_TABLE_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    # 2. Drop enums
    for enum_name in DOWN_ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {enum_name} CASCADE;")
