"""Cloudinary images and durable cleanup of replaced/abandoned uploads."""
from alembic import op

revision = "0009_cloudinary_images"
down_revision = "0008_catalog_images"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("foods", "exercises", "meals", "trainings"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN image_public_id text")
    for table in ("meals", "trainings"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN image_url text")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_image_url CHECK (image_url IS NULL OR image_url LIKE 'https://%')")
    op.execute("""CREATE TABLE image_cleanup (
        public_id text PRIMARY KEY,
        cloud_name text NOT NULL,
        available_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX ix_image_cleanup_available_at ON image_cleanup (available_at)")


def downgrade():
    op.drop_table("image_cleanup")
    for table in ("meals", "trainings"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_image_url, DROP COLUMN image_url")
    for table in ("foods", "exercises", "meals", "trainings"):
        op.drop_column(table, "image_public_id")
