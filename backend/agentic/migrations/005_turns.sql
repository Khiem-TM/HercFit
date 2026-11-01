-- One structured record per conversation turn (no message or reply text).
-- Versioned like executions: a turn confirmed later replaces its pending state.
CREATE TABLE IF NOT EXISTS agent_turn_records (
    run_id text PRIMARY KEY,
    session_id varchar(128) NOT NULL,
    session_generation bigint NOT NULL,
    user_id uuid NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    occurred_at timestamptz NOT NULL,
    data jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_turn_records_session ON agent_turn_records(session_id);
