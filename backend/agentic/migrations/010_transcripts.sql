-- User-visible history is independent from execution checkpoints and model memory.
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS transcript_migrated boolean NOT NULL DEFAULT false;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS memory_consent_version bigint NOT NULL DEFAULT 0;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS memory_cleanup_pending boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS agent_transcript_messages (
    seq bigserial PRIMARY KEY,
    session_id varchar(128) NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    message_id text NOT NULL,
    role text NOT NULL CHECK (role IN ('human', 'ai')),
    content jsonb NOT NULL,
    name text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(session_id, message_id)
);
CREATE INDEX IF NOT EXISTS agent_transcript_session_seq ON agent_transcript_messages(session_id, seq);
