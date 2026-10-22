"""Atomic replay of authenticated business writes."""
from alembic import op

revision = "0002_api_idempotency"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE api_idempotency (
            user_id uuid NOT NULL REFERENCES users(id),
            key varchar(128) NOT NULL,
            request_hash varchar(64) NOT NULL,
            status_code integer NOT NULL,
            body jsonb,
            headers jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key)
        )
    """)


def downgrade():
    op.execute("DROP TABLE api_idempotency")
