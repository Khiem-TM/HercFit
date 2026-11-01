"""Căn cứ dinh dưỡng theo khẩu phần và đơn vị đo gia dụng cho thực phẩm trong catalog.

* food_serving_unit có thêm PORTION: dưỡng chất mô tả một khẩu phần (suất) có thể
  chưa biết khối lượng gam. Nhiều bảng thành phần món ăn Việt Nam công bố
  giá trị theo suất, không được nhân tỉ lệ như thể chúng tính theo 100 g.
* foods.portion_weight_g ghi (tuỳ chọn) khối lượng gam của suất đó.
* foods.portions liệt kê đơn vị đo gia dụng, ví dụ {"label": "1 tô lớn",
  "quantity": 650, "unit": "G"}, để "một tô phở" ánh xạ ra một lượng đo được.
"""
from alembic import op

revision = "0013_food_portions"
down_revision = "0012_security_profile"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL 12+ cho phép ADD VALUE bên trong transaction miễn là giá trị mới
    # không được dùng trước khi commit; không có gì bên dưới dùng PORTION (sửa dữ liệu là một script).
    op.execute("ALTER TYPE food_serving_unit ADD VALUE IF NOT EXISTS 'PORTION'")
    op.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS portions jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE foods ADD COLUMN IF NOT EXISTS portion_weight_g numeric(12,4)")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portions")
    op.execute("ALTER TABLE foods ADD CONSTRAINT ck_foods_portions CHECK (jsonb_typeof(portions) = 'array')")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portion_weight")
    op.execute("ALTER TABLE foods ADD CONSTRAINT ck_foods_portion_weight "
               "CHECK (portion_weight_g IS NULL OR (portion_weight_g > 0 AND portion_weight_g < 100000))")


def downgrade():
    # PostgreSQL không xoá được một giá trị enum; các dòng dùng PORTION phải được chuyển đổi trước.
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portion_weight")
    op.execute("ALTER TABLE foods DROP CONSTRAINT IF EXISTS ck_foods_portions")
    op.execute("ALTER TABLE foods DROP COLUMN IF EXISTS portion_weight_g")
    op.execute("ALTER TABLE foods DROP COLUMN IF EXISTS portions")
