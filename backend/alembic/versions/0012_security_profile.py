"""Drop stored Google tokens, cascade idempotency rows, add users.sex for energy targets.

* HercFit only needs the Google identity. Access/refresh tokens written by
  earlier versions are credentials the application never uses; they are erased.
* api_idempotency referenced users without ON DELETE CASCADE, which blocked a
  user's right to have their account erased.
* users.sex (biological sex, optional) is an input of the Mifflin-St Jeor BMR.
"""
from alembic import op

revision = "0012_security_profile"
down_revision = "0011_kg_profile"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE oauth_accounts SET access_token = NULL, refresh_token = NULL, token_expires_at = NULL "
               "WHERE access_token IS NOT NULL OR refresh_token IS NOT NULL OR token_expires_at IS NOT NULL")
    op.execute("ALTER TABLE api_idempotency DROP CONSTRAINT IF EXISTS api_idempotency_user_id_fkey")
    op.execute("ALTER TABLE api_idempotency ADD CONSTRAINT api_idempotency_user_id_fkey "
               "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_idempotency_created ON api_idempotency (created_at)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sex varchar(10)")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_sex")
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_sex CHECK (sex IS NULL OR sex IN ('MALE', 'FEMALE'))")


def downgrade():
    # Erased provider tokens cannot be restored; only the structural changes are reverted.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_sex")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sex")
    op.execute("DROP INDEX IF EXISTS ix_api_idempotency_created")
    op.execute("ALTER TABLE api_idempotency DROP CONSTRAINT IF EXISTS api_idempotency_user_id_fkey")
    op.execute("ALTER TABLE api_idempotency ADD CONSTRAINT api_idempotency_user_id_fkey "
               "FOREIGN KEY (user_id) REFERENCES users(id)")
