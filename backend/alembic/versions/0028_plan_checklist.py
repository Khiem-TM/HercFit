"""Kế hoạch tối giản: bỏ lịch bữa ăn, lịch tập có checklist hoàn thành theo buổi.

* Bỏ meal_plans / meal_plan_entries / meal_plan_items và liên kết meals.source_entry_id tới chúng.
* training_plan_entries.completed_at: thời điểm người dùng tick buổi tập (chỉ trong ngày của buổi, không hoàn tác);
  lúc tick, buổi tập thật được ghi vào nhật ký với source_entry_id = buổi kế hoạch.

Không có downgrade cho lịch bữa ăn: khôi phục bằng bản sao lưu chụp trước 0028.
"""
from alembic import op

revision = "0028_plan_checklist"
down_revision = "0027_health_points"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE meals DROP COLUMN IF EXISTS source_entry_id")
    op.execute("DROP TABLE IF EXISTS meal_plan_items, meal_plan_entries, meal_plans")
    op.execute("ALTER TABLE training_plan_entries ADD COLUMN completed_at timestamptz")


def downgrade():
    raise NotImplementedError("0028_plan_checklist is irreversible: restore the pre-0028 database backup")
