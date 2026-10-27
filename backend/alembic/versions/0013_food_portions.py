"""Per-portion nutrient basis and household portions for catalog foods.

* food_serving_unit gains PORTION: nutrients describe one serving (suất) whose
  gram weight may be unknown. Many Vietnamese dish composition tables publish
  values per serving, which must not be scaled as if they were per 100 g.
* foods.portion_weight_g optionally records the gram weight of that serving.
* foods.portions lists household measures, e.g. {"label": "1 tô lớn",
  "quantity": 650, "unit": "G"}, so "một tô phở" maps to a measured amount.
"""
from alembic import op

revision = "0013_food_portions"
down_revision = "0012_security_profile"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL 12+ allows ADD VALUE inside a transaction as long as the new value
    # is not used before commit; nothing below uses PORTION (data repair is a script).
    op.execute("ALTER TYPE food_serving_unit ADD VALUE IF NOT EXISTS 'PORTION'")
    op.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS portions jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS portion_weight_g numeric(12,4)")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portions")
    op.execute("ALTER TABLE foods ADD CONSTRAINT ck_foods_portions CHECK (jsonb_typeof(portions) = 'array')")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portion_weight")
    op.execute("ALTER TABLE foods ADD CONSTRAINT ck_foods_portion_weight "
               "CHECK (portion_weight_g IS NULL OR (portion_weight_g > 0 AND portion_weight_g < 100000))")


def downgrade():
    # PostgreSQL cannot drop an enum value; rows using PORTION must be converted first.
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portion_weight")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portions")
    op.execute("ALTER TABLE foods DROP COLUMN IF EXISTS portion_weight_g")
    op.execute("ALTER TABLE foods DROP COLUMN IF EXISTS portions")
