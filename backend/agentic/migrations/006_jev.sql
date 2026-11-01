-- Counts are business-run durable; no input messages, prompts or evidence are saved.
CREATE TABLE IF NOT EXISTS agent_jev_runs (
    run_id text PRIMARY KEY,
    session_id varchar(128) NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    mode text NOT NULL CHECK (mode IN ('shadow','enforce')),
    routing integer NOT NULL DEFAULT 0 CHECK (routing BETWEEN 0 AND 1),
    research integer NOT NULL DEFAULT 0 CHECK (research BETWEEN 0 AND 2),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_jev_runs_session ON agent_jev_runs(session_id);
CREATE TABLE IF NOT EXISTS agent_jev_evaluations (
    run_id text NOT NULL REFERENCES agent_jev_runs(run_id) ON DELETE CASCADE,
    phase text NOT NULL CHECK (phase IN ('routing','local','final')),
    fingerprint char(64) NOT NULL,
    evaluation_id uuid NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','complete')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (run_id,phase,fingerprint)
);
