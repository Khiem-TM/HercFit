"""Capture knowledge graph projections atomically with source writes."""

from alembic import op

from core.graph_outbox import CHILD_TABLES, SOURCE_TABLES, installation_statements

revision = "0004_knowledge_graph"
down_revision = "0003_agent_journal_compat"
branch_labels = None
depends_on = None


def upgrade():
    for statement in installation_statements():
        op.execute(statement)


def downgrade():
    for table in (*SOURCE_TABLES.values(), *CHILD_TABLES.values()):
        op.execute(f"DROP TRIGGER IF EXISTS kg_capture ON {table}")
    op.execute("DROP FUNCTION IF EXISTS kg_enqueue_snapshot()")
    op.execute("DROP FUNCTION IF EXISTS kg_capture_backend()")
    op.execute("DROP FUNCTION IF EXISTS kg_publish_backend(text, jsonb, boolean)")
    op.execute("DROP FUNCTION IF EXISTS kg_allowlisted_payload(text, jsonb)")
    op.execute("DROP FUNCTION IF EXISTS kg_training_profile(jsonb)")
    # Retain envelopes and revision/tombstone state. The outbox may share a DB
    # with the agent service, and deleting it would lose committed work.
