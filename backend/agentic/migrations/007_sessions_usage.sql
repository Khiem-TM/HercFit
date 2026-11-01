-- Session leases replace advisory locks held on a pooled connection for a whole run.
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS lease_token uuid;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS lease_until timestamptz;
-- Sidebar metadata, written at the end of each run (no checkpoint read per session).
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_message text;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_interaction_at timestamptz;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS message_count integer;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_status text;
CREATE INDEX IF NOT EXISTS agent_sessions_user_recent
    ON agent_sessions (user_id, (COALESCE(last_interaction_at, created_at)) DESC);
-- Only threads touched by a run since their last journal need reconciliation.
ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS needs_reconcile boolean NOT NULL DEFAULT false;
ALTER TABLE agent_threads ADD COLUMN IF NOT EXISTS last_run_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS agent_threads_reconcile ON agent_threads (last_run_at) WHERE needs_reconcile;
CREATE INDEX IF NOT EXISTS agent_threads_session ON agent_threads (session_id);
-- Durable per-user daily usage for abuse and cost limits (shared by all workers).
CREATE TABLE IF NOT EXISTS agent_usage_daily (
    user_id uuid NOT NULL,
    day date NOT NULL,
    turns integer NOT NULL DEFAULT 0,
    input_tokens bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, day)
);
