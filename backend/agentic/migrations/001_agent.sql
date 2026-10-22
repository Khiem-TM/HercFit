CREATE TABLE IF NOT EXISTS agent_schema_version (version integer PRIMARY KEY);
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id varchar(128) PRIMARY KEY,
    user_id uuid NOT NULL,
    thread_id text,
    revision integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS agent_threads (thread_id text PRIMARY KEY, session_id varchar(128) NOT NULL REFERENCES agent_sessions(session_id));
CREATE TABLE IF NOT EXISTS agent_actions (
    action_id uuid PRIMARY KEY,
    session_id varchar(128) NOT NULL REFERENCES agent_sessions(session_id),
    user_id uuid NOT NULL,
    status text NOT NULL,
    data jsonb NOT NULL,
    response jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_one_pending_action ON agent_actions(session_id)
    WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS agent_research (
    research_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    session_id varchar(128) NOT NULL REFERENCES agent_sessions(session_id),
    resource_id uuid,
    data jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO agent_schema_version VALUES (1) ON CONFLICT DO NOTHING;
