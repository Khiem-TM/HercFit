-- =============================================================================
-- HercFit PostgreSQL Schema Initialization
-- Automatically executed on first container startup via /docker-entrypoint-initdb.d
-- Note: LangGraph checkpoint & store tables are auto-created by AsyncPostgresSaver/Store
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- 1. Users & Body Metrics (modules/users/models.py)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(64) PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    age INTEGER,
    height_cm DOUBLE PRECISION,
    fitness_goal VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS body_metrics (
    metric_id VARCHAR(64) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    weight_kg DOUBLE PRECISION NOT NULL,
    body_fat_pct DOUBLE PRECISION,
    muscle_mass_kg DOUBLE PRECISION,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_body_metrics_user_recorded
    ON body_metrics(user_id, recorded_at DESC);

-- -----------------------------------------------------------------------------
-- 2. Nutrition & Meals (modules/nutrition/models.py)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meals (
    meal_id VARCHAR(64) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    calories INTEGER NOT NULL,
    protein_g DOUBLE PRECISION NOT NULL DEFAULT 0,
    carbs_g DOUBLE PRECISION NOT NULL DEFAULT 0,
    fat_g DOUBLE PRECISION NOT NULL DEFAULT 0,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meals_user_logged
    ON meals(user_id, logged_at DESC);

-- -----------------------------------------------------------------------------
-- 3. Workouts (modules/workouts/models.py)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS workout_plans (
    plan_id VARCHAR(64) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    days_per_week INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workout_plans_user
    ON workout_plans(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workout_sessions (
    session_id VARCHAR(64) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    workout_name VARCHAR(255) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    calories_burned INTEGER,
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workout_sessions_user_performed
    ON workout_sessions(user_id, performed_at DESC);

-- -----------------------------------------------------------------------------
-- 4. Habits & Check-ins (modules/habits/models.py)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS habits (
    habit_id VARCHAR(64) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    target_value DOUBLE PRECISION NOT NULL,
    unit VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_habits_user
    ON habits(user_id);

CREATE TABLE IF NOT EXISTS habit_checkins (
    checkin_id VARCHAR(64) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    habit_id VARCHAR(64) NOT NULL REFERENCES habits(habit_id) ON DELETE CASCADE,
    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    value DOUBLE PRECISION NOT NULL,
    checkin_date DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (habit_id, checkin_date)
);

CREATE INDEX IF NOT EXISTS idx_habit_checkins_user_date
    ON habit_checkins(user_id, checkin_date DESC);

-- Seed default development user
INSERT INTO users (user_id, full_name, age, height_cm, fitness_goal)
VALUES ('default-user', 'Health User', 25, 172.0, 'muscle_gain')
ON CONFLICT (user_id) DO NOTHING;

