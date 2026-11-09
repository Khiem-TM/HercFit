"""Dashboard mới: vòng ngực/eo/hông, cài đặt đồng bộ Google Health, loại thông báo nhắc nhở.

* body_metrics: chest_cm, waist_cm, hip_cm (Google không có các chỉ số này nên luôn lưu trong HercFit).
  Một số đo chỉ có vòng eo (không cân lại) là hợp lệ: ràng buộc "có ít nhất một số đo" tính cả ba cột mới.
* health_connections.sync_groups: nhóm dữ liệu người dùng tắt đồng bộ ({"hrv": false}); thiếu khoá = bật.
  sync_frequency: hourly (vòng nền mỗi giờ), open (khi mở ứng dụng), manual (chỉ khi bấm "Đồng bộ ngay").
* user_notifications.kind thêm reminder (nhắc buổi tập, bữa ăn), summary (tổng kết tuần), proposal
  (đề xuất điều chỉnh lịch khi điểm sẵn sàng thấp, buổi bị lỡ).
"""
from alembic import op

revision = "0030_dashboard_settings"
down_revision = "0029_user_notifications"
branch_labels = depends_on = None

CIRCUMFERENCES = ("chest_cm", "waist_cm", "hip_cm")
OLD_KINDS = "('briefing', 'insight', 'praise', 'data_quality')"
NEW_KINDS = "('briefing', 'insight', 'praise', 'data_quality', 'reminder', 'summary', 'proposal')"


def upgrade():
    for column in CIRCUMFERENCES:
        op.execute(f"ALTER TABLE body_metrics ADD COLUMN {column} numeric(6, 2)")
        op.execute(f"ALTER TABLE body_metrics ADD CONSTRAINT ck_body_metrics_{column} "
                   f"CHECK ({column} > 0 AND {column} < 400)")
    op.execute("ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS ck_body_metrics_any_measurement")
    op.execute("ALTER TABLE body_metrics ADD CONSTRAINT ck_body_metrics_any_measurement CHECK ("
               "weight_kg IS NOT NULL OR height_cm IS NOT NULL OR body_fat_pct IS NOT NULL "
               "OR muscle_mass_kg IS NOT NULL OR chest_cm IS NOT NULL OR waist_cm IS NOT NULL OR hip_cm IS NOT NULL)")

    op.execute("ALTER TABLE health_connections ADD COLUMN sync_groups jsonb NOT NULL DEFAULT '{}'::jsonb "
               "CONSTRAINT ck_health_connections_sync_groups CHECK (jsonb_typeof(sync_groups) = 'object')")
    op.execute("ALTER TABLE health_connections ADD COLUMN sync_frequency varchar(10) NOT NULL DEFAULT 'hourly' "
               "CONSTRAINT ck_health_connections_sync_frequency CHECK (sync_frequency IN ('hourly', 'open', 'manual'))")

    op.execute("ALTER TABLE user_notifications DROP CONSTRAINT IF EXISTS user_notifications_kind_check")
    op.execute(f"ALTER TABLE user_notifications ADD CONSTRAINT user_notifications_kind_check CHECK (kind IN {NEW_KINDS})")


def downgrade():
    op.execute("DELETE FROM user_notifications WHERE kind IN ('reminder', 'summary', 'proposal')")
    op.execute("ALTER TABLE user_notifications DROP CONSTRAINT IF EXISTS user_notifications_kind_check")
    op.execute(f"ALTER TABLE user_notifications ADD CONSTRAINT user_notifications_kind_check CHECK (kind IN {OLD_KINDS})")

    op.execute("ALTER TABLE health_connections DROP COLUMN IF EXISTS sync_frequency")
    op.execute("ALTER TABLE health_connections DROP COLUMN IF EXISTS sync_groups")

    # Số đo chỉ có vòng đo không còn chỗ chứa sau khi bỏ cột.
    op.execute("DELETE FROM body_metrics WHERE weight_kg IS NULL AND height_cm IS NULL AND body_fat_pct IS NULL "
               "AND muscle_mass_kg IS NULL")
    op.execute("ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS ck_body_metrics_any_measurement")
    op.execute("ALTER TABLE body_metrics ADD CONSTRAINT ck_body_metrics_any_measurement CHECK ("
               "weight_kg IS NOT NULL OR height_cm IS NOT NULL OR body_fat_pct IS NOT NULL OR muscle_mass_kg IS NOT NULL)")
    for column in CIRCUMFERENCES:
        op.execute(f"ALTER TABLE body_metrics DROP CONSTRAINT IF EXISTS ck_body_metrics_{column}")
        op.execute(f"ALTER TABLE body_metrics DROP COLUMN IF EXISTS {column}")
