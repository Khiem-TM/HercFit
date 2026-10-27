"""Project users.age and the validated training profile onto the graph User."""
from alembic import op

from core.graph_outbox import installation_statements

revision = "0011_kg_profile"
down_revision = "0010_observability"
branch_labels = None
depends_on = None


def upgrade():
    for statement in installation_statements():
        op.execute(statement)
    # Publish current profiles once; later edits are captured by the trigger.
    op.execute("SELECT kg_publish_backend('User', to_jsonb(u)) FROM users u")


def downgrade():
    for statement in installation_statements(profile=False):
        op.execute(statement)
    op.execute("DROP FUNCTION IF EXISTS kg_training_profile(jsonb)")
