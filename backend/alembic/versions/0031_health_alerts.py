"""Thông báo theo bộ luật chỉ số sức khoẻ và đánh giá chất lượng ngày.

* user_notifications.kind thêm alert (chỉ số vượt ngưỡng của bộ luật y tế) và review (đánh giá ngày).
  Các loại cũ (briefing, insight, praise, data_quality, summary) không còn được tạo nhưng vẫn hợp lệ để
  thông báo đã gửi trước đây còn đọc được tới khi hết hạn.
"""
from alembic import op

revision = "0031_health_alerts"
down_revision = "0030_dashboard_settings"
branch_labels = depends_on = None

OLD_KINDS = "('briefing', 'insight', 'praise', 'data_quality', 'reminder', 'summary', 'proposal')"
NEW_KINDS = "('briefing', 'insight', 'praise', 'data_quality', 'reminder', 'summary', 'proposal', 'alert', 'review')"


def upgrade():
    op.execute("ALTER TABLE user_notifications DROP CONSTRAINT IF EXISTS user_notifications_kind_check")
    op.execute(f"ALTER TABLE user_notifications ADD CONSTRAINT user_notifications_kind_check CHECK (kind IN {NEW_KINDS})")


def downgrade():
    op.execute("DELETE FROM user_notifications WHERE kind IN ('alert', 'review')")
    op.execute("ALTER TABLE user_notifications DROP CONSTRAINT IF EXISTS user_notifications_kind_check")
    op.execute(f"ALTER TABLE user_notifications ADD CONSTRAINT user_notifications_kind_check CHECK (kind IN {OLD_KINDS})")
