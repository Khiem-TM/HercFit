"""Research alias resolution and atomic finalization receipts."""
from alembic import op
revision = '0005_research_catalog'
down_revision = '0004_knowledge_graph'
branch_labels = depends_on = None

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    for domain in ('foods', 'exercises'):
        op.execute(f'''CREATE TABLE {domain}_aliases (
            entity_id uuid NOT NULL REFERENCES {domain}(id) ON DELETE CASCADE,
            normalized_alias text NOT NULL, PRIMARY KEY(entity_id, normalized_alias))''')
        op.execute(f'CREATE INDEX ix_{domain}_aliases_text ON {domain}_aliases(normalized_alias)')
        op.execute(f'CREATE INDEX ix_{domain}_trgm ON {domain} USING gin(normalized_search_text gin_trgm_ops)')
    op.execute('''CREATE TABLE research_finalizations (
        owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        candidate_id uuid NOT NULL, candidate_revision integer NOT NULL CHECK(candidate_revision>0),
        digest text NOT NULL, domain text NOT NULL CHECK(domain IN ('foods','exercises')),
        command jsonb NOT NULL, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(owner_id,candidate_id,candidate_revision))''')
    # A domain lock also covers direct SQL imports and UI changes. Catalog writes
    # are infrequent; coarse locking avoids alias/rename lock-order deadlocks.
    op.execute('''CREATE FUNCTION research_catalog_lock() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN PERFORM pg_advisory_xact_lock(hashtextextended('catalog:' || TG_ARGV[0],0));
        RETURN NULL; END $$''')
    for domain in ('foods', 'exercises'):
        for table in (domain, domain+'_aliases'):
            op.execute(f"CREATE TRIGGER research_lock BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION research_catalog_lock('{domain}')")

def downgrade():
    # Deliberately retain user provenance/receipts; destructive removal is manual.
    raise RuntimeError('Research data is retained. Roll back application flags, not provenance tables.')
