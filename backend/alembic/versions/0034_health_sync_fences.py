"""Fence in-flight syncs and version local edits before acknowledging a push."""
from alembic import op

revision = "0034_health_sync_fences"
down_revision = "0033_context_graph_sync"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE health_connections ADD COLUMN sync_generation bigint NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE health_points ADD COLUMN revision bigint NOT NULL DEFAULT 1")
    op.execute("""CREATE TABLE health_push_cleanup (
        user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        data_type varchar(48) NOT NULL, remote_name varchar(300) NOT NULL,
        PRIMARY KEY (user_id, data_type, remote_name))""")


def downgrade():
    op.execute("DROP TABLE health_push_cleanup")
    op.execute("ALTER TABLE health_points DROP COLUMN revision")
    op.execute("ALTER TABLE health_connections DROP COLUMN sync_generation")
