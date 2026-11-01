CREATE TABLE IF NOT EXISTS agent_research_budgets (
    run_id uuid PRIMARY KEY, user_id uuid NOT NULL, session_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
    web integer NOT NULL DEFAULT 0, search integer NOT NULL DEFAULT 0,
    llm integer NOT NULL DEFAULT 0, rounds integer NOT NULL DEFAULT 0,
    documents jsonb NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS agent_research_rate ON agent_research_budgets(user_id,created_at);
