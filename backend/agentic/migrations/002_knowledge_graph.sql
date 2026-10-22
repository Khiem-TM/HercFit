CREATE TABLE IF NOT EXISTS kg_outbox (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    owner_id text,
    aggregate_version bigint NOT NULL,
    operation text NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload jsonb NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,
    last_error text,
    UNIQUE(source, aggregate_type, aggregate_id, aggregate_version, operation)
);
CREATE INDEX IF NOT EXISTS kg_outbox_pending ON kg_outbox(available_at, occurred_at)
    WHERE delivered_at IS NULL;

-- Kept independently of agent_sessions so clearing a conversation cannot
-- resurrect its old events, even when its public session_id is reused.
CREATE TABLE IF NOT EXISTS agent_session_generations (
    session_id varchar(128) PRIMARY KEY,
    user_id uuid NOT NULL,
    generation bigint NOT NULL DEFAULT 1,
    deleted boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO agent_session_generations(session_id,user_id)
    SELECT session_id,user_id FROM agent_sessions ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS agent_session_generation_owner ON agent_session_generations(user_id);
ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS kg_checkpoint_id text;
ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS kg_checked_at timestamptz NOT NULL DEFAULT 'epoch';
CREATE TABLE IF NOT EXISTS agent_execution_records (
    execution_id uuid PRIMARY KEY,
    session_id varchar(128) NOT NULL,
    session_generation bigint NOT NULL,
    user_id uuid NOT NULL,
    run_id text NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    occurred_at timestamptz NOT NULL,
    data jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_execution_records_session ON agent_execution_records(session_id);
INSERT INTO agent_schema_version VALUES (2) ON CONFLICT DO NOTHING;
