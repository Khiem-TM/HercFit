"""Optional catalog images for foods and exercises (shown on confirmation cards)."""

from alembic import op

revision = "0008_catalog_images"
down_revision = "0007_training_v2"
branch_labels = None
depends_on = None

IMAGE_CHECK = "image_url IS NULL OR image_url ~ '^(https://[^[:space:]]+|/[A-Za-z0-9._~/-]+)$'"


def upgrade():
    for table in ("foods", "exercises"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN image_url text")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_image_url CHECK ({IMAGE_CHECK})")


def downgrade():
    for table in ("foods", "exercises"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_image_url, DROP COLUMN IF EXISTS image_url")
