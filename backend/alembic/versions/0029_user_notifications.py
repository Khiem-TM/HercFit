"""Thông báo trong ứng dụng (briefing buổi sáng, insight, lời khen, nhắc dữ liệu) và consent "proactive".

* user_notifications: một hộp thư cho mỗi người dùng. dedup_key (vd. 'briefing:2026-11-08',
  'insight:LOAD_HIGH:2026-W45') là duy nhất theo người dùng, nên nhiều tiến trình cùng đánh giá
  cũng chỉ tạo một thông báo. payload giữ ảnh chụp trạng thái/lý do/phiên bản thuật toán đã báo
  (để kiểm toán), không giữ chuỗi số đo thô. Không có loại "khẩn cấp y khoa".
* user_consents.purpose thêm 'proactive': người dùng tự bật thông báo chủ động, tách khỏi quyền
  của trợ lý ('assistant'); thu hồi 'proactive' không dọn dữ liệu của trợ lý.
"""
from alembic import op

revision = "0029_user_notifications"
down_revision = "0028_plan_checklist"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE user_notifications (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind varchar(16) NOT NULL CHECK (kind IN ('briefing', 'insight', 'praise', 'data_quality')),
            code varchar(48) NOT NULL,
            priority smallint NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
            local_date date NOT NULL,
            dedup_key varchar(120) NOT NULL,
            title text NOT NULL,
            body text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            seen_at timestamptz,
            dismissed_at timestamptz,
            expires_at timestamptz,
            CONSTRAINT uq_user_notifications_dedup UNIQUE (user_id, dedup_key)
        )""")
    op.execute("CREATE INDEX ix_user_notifications_user_created ON user_notifications (user_id, created_at DESC)")
    op.execute("ALTER TABLE user_consents DROP CONSTRAINT IF EXISTS ck_user_consents_purpose")
    op.execute("ALTER TABLE user_consents ADD CONSTRAINT ck_user_consents_purpose "
               "CHECK (purpose IN ('assistant', 'proactive'))")


def downgrade():
    op.execute("DELETE FROM user_consents WHERE purpose = 'proactive'")
    op.execute("ALTER TABLE user_consents DROP CONSTRAINT IF EXISTS ck_user_consents_purpose")
    op.execute("ALTER TABLE user_consents ADD CONSTRAINT ck_user_consents_purpose CHECK (purpose IN ('assistant'))")
    op.execute("DROP TABLE IF EXISTS user_notifications")
