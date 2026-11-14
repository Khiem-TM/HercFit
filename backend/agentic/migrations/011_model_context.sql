ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS memory_cache_cleanup_pending boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS agent_model_context (
    session_id varchar(128) PRIMARY KEY REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    generation bigint NOT NULL,
    data jsonb NOT NULL,
    expires_at timestamptz NOT NULL
);
