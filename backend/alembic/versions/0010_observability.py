"""Durable observability lineage for asynchronous projections and ingestion."""
from alembic import op
revision = '0010_observability'
down_revision = '0009_cloudinary_images'
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE kg_outbox ADD COLUMN IF NOT EXISTS trace_context jsonb DEFAULT NULLIF(current_setting('hercfit.trace_context', true), '')::jsonb")
    op.execute("ALTER TABLE knowledge_jobs ADD COLUMN IF NOT EXISTS trace_context jsonb DEFAULT NULLIF(current_setting('hercfit.trace_context', true), '')::jsonb")


def downgrade():
    op.execute('ALTER TABLE knowledge_jobs DROP COLUMN IF EXISTS trace_context')
    # Shared with the independently migrated agent service; leave its optional column in place.
