"""Chiếu users.age và hồ sơ tập luyện đã kiểm tra lên node User của graph."""
from alembic import op
from core.graph_outbox import installation_statements

revision = "0011_kg_profile"
down_revision = "0010_observability"
branch_labels = None
depends_on = None


def upgrade():
    for statement in installation_statements():
        op.execute(statement)
    # Phát hồ sơ hiện tại một lần; các lần sửa sau được trigger ghi nhận.
    op.execute("SELECT kg_publish_backend('User', to_jsonb(u)) FROM users u")


def downgrade():
    for statement in installation_statements(profile=False):
        op.execute(statement)
    op.execute("DROP FUNCTION IF EXISTS kg_training_profile(jsonb)")
