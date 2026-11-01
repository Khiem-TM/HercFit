-- 003 added `documents` inside CREATE TABLE IF NOT EXISTS, so databases whose budget table
-- predates it never received the column (research failed with UndefinedColumn).
ALTER TABLE agent_research_budgets ADD COLUMN IF NOT EXISTS documents jsonb NOT NULL DEFAULT '[]'::jsonb;
