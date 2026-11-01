-- All columns are optional and compatible with jobs/actions created before tracing.
ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS trace_context jsonb;
ALTER TABLE kg_outbox ADD COLUMN IF NOT EXISTS trace_context jsonb
    DEFAULT NULLIF(current_setting('hercfit.trace_context', true), '')::jsonb;
