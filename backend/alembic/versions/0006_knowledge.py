"""Approved document revisions, isolated embedding profiles and durable jobs."""
from alembic import op
revision='0006_knowledge'
down_revision='0005_research_catalog'
branch_labels=depends_on=None

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('''CREATE TABLE knowledge_profiles (
        id text PRIMARY KEY, model text NOT NULL, dimension integer NOT NULL CHECK(dimension>0),
        active boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('CREATE UNIQUE INDEX knowledge_one_profile ON knowledge_profiles(active) WHERE active')
    op.execute('''CREATE TABLE knowledge_documents (
        id uuid PRIMARY KEY, source_key text UNIQUE NOT NULL, title text NOT NULL,
        source_url text, license text NOT NULL, active_revision uuid)''')
    op.execute('''CREATE TABLE knowledge_revisions (
        id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES knowledge_documents(id),
        version integer NOT NULL, content_hash text NOT NULL, content text NOT NULL,
        metadata jsonb NOT NULL DEFAULT '{}', review_status text NOT NULL DEFAULT 'INGESTED'
        CHECK(review_status IN ('DISCOVERED','INGESTED','REVIEWED','APPROVED','REJECTED','STALE','SUPERSEDED')),
        reviewer text, reviewed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE(document_id,version), UNIQUE(document_id,content_hash))''')
    op.execute('ALTER TABLE knowledge_documents ADD CONSTRAINT knowledge_active_fk FOREIGN KEY(active_revision) REFERENCES knowledge_revisions(id)')
    op.execute('''CREATE TABLE knowledge_chunks (
        id uuid PRIMARY KEY, revision_id uuid NOT NULL REFERENCES knowledge_revisions(id),
        position integer NOT NULL, heading text, page integer, content text NOT NULL,
        search_vector tsvector NOT NULL, UNIQUE(revision_id,position))''')
    op.execute('CREATE INDEX knowledge_fts ON knowledge_chunks USING gin(search_vector)')
    op.execute('''CREATE TABLE knowledge_embeddings (
        chunk_id uuid NOT NULL REFERENCES knowledge_chunks(id), profile_id text NOT NULL REFERENCES knowledge_profiles(id),
        embedding vector NOT NULL, PRIMARY KEY(chunk_id,profile_id))''')
    op.execute('''CREATE TABLE knowledge_jobs (
        id uuid PRIMARY KEY, revision_id uuid NOT NULL REFERENCES knowledge_revisions(id),
        profile_id text NOT NULL REFERENCES knowledge_profiles(id),
        status text NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','RUNNING','INDEXED','FAILED')),
        attempts integer NOT NULL DEFAULT 0, lease_token uuid, lease_until timestamptz,
        available_at timestamptz NOT NULL DEFAULT now(), error_code text,
        UNIQUE(revision_id,profile_id))''')
    op.execute('CREATE INDEX knowledge_jobs_poll ON knowledge_jobs(status,available_at)')
    op.execute('''CREATE FUNCTION knowledge_vector_dimension() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF vector_dims(NEW.embedding) <> (SELECT dimension FROM knowledge_profiles WHERE id=NEW.profile_id)
        THEN RAISE EXCEPTION 'Embedding dimension mismatch'; END IF; RETURN NEW; END $$''')
    op.execute('CREATE TRIGGER knowledge_dimension BEFORE INSERT OR UPDATE ON knowledge_embeddings FOR EACH ROW EXECUTE FUNCTION knowledge_vector_dimension()')

def downgrade():
    raise RuntimeError('Knowledge revisions are retained; disable RAG to roll back.')
