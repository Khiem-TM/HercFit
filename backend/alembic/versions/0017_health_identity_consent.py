"""Nền tảng sức khoẻ M2: danh tính và fencing của kết nối, và consent thành bản ghi riêng.

* health_connections có thêm health user id của nhà cung cấp (webhook định tuyến theo nó),
  thế hệ kết nối (tăng khi kết nối lại/ngắt kết nối để fence các job
  đã cũ), lease epoch (fencing token cho mọi lệnh ghi mà một lần sync thực hiện) và
  phiên bản API mà kết nối đọc.
* user_consents là nguồn sự thật duy nhất về những gì trợ lý được đọc;
  consent_events giữ lịch sử chỉ-ghi-thêm. Consent của trợ lý được điền
  từ health_connections.share_with_assistant, cột này chỉ còn để quay lui.
* domain_events là outbox giao dịch cho các dữ kiện nghiệp vụ (ví dụ consent.changed);
  mỗi consumer ghi những gì nó đã xử lý vào domain_event_deliveries, nên các sự kiện
  commit không theo thứ tự id không bao giờ bị bỏ qua.
* Cổng consent của knowledge graph (kg_device_consent) giờ đọc user_consents,
  và thay đổi consent phát lại dữ liệu thiết bị trong cùng transaction.

Chỉ cộng thêm; downgrade chỉ xoá những gì revision này đã tạo.
"""
from alembic import op

from core.graph_outbox import installation_statements

revision = "0017_health_identity_consent"
down_revision = "0016_gym_quick_log"
branch_labels = depends_on = None

POLICY_VERSION = "2026-11-01"


def upgrade():
    op.execute("""
        ALTER TABLE health_connections
            ADD COLUMN IF NOT EXISTS health_user_id varchar(255),
            ADD COLUMN IF NOT EXISTS generation bigint DEFAULT 1 NOT NULL,
            ADD COLUMN IF NOT EXISTS lease_epoch bigint DEFAULT 0 NOT NULL,
            ADD COLUMN IF NOT EXISTS api_version varchar(8) DEFAULT 'v4' NOT NULL""")
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE health_connections ADD CONSTRAINT ck_health_connections_api_version
                CHECK (api_version IN ('v4', 'v4beta'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$""")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_health_connections_health_user
            ON health_connections (provider, health_user_id) WHERE health_user_id IS NOT NULL""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_consents (
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose varchar(30) NOT NULL,
            data_group varchar(30) NOT NULL,
            granted boolean DEFAULT false NOT NULL,
            version bigint NOT NULL,
            policy_version varchar(20) NOT NULL,
            changed_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (user_id, purpose, data_group),
            CONSTRAINT ck_user_consents_purpose CHECK (purpose IN ('assistant')),
            CONSTRAINT ck_user_consents_data_group CHECK (data_group IN ('device', 'sensitive')),
            CONSTRAINT ck_user_consents_version CHECK (version >= 1)
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS consent_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose varchar(30) NOT NULL,
            data_group varchar(30) NOT NULL,
            granted boolean NOT NULL,
            version bigint NOT NULL,
            policy_version varchar(20) NOT NULL,
            actor varchar(20) NOT NULL,
            occurred_at timestamptz DEFAULT now() NOT NULL,
            CONSTRAINT ck_consent_events_actor CHECK (actor IN ('USER', 'SYSTEM', 'MIGRATION'))
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_consent_events_user ON consent_events (user_id, occurred_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS domain_events (
            id bigserial PRIMARY KEY,
            topic varchar(60) NOT NULL,
            user_id uuid REFERENCES users(id) ON DELETE CASCADE,
            payload jsonb DEFAULT '{}'::jsonb NOT NULL,
            occurred_at timestamptz DEFAULT now() NOT NULL,
            CONSTRAINT ck_domain_events_payload CHECK (jsonb_typeof(payload) = 'object')
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_domain_events_topic ON domain_events (topic, occurred_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS domain_event_deliveries (
            consumer varchar(60) NOT NULL,
            event_id bigint NOT NULL REFERENCES domain_events(id) ON DELETE CASCADE,
            delivered_at timestamptz DEFAULT now() NOT NULL,
            PRIMARY KEY (consumer, event_id)
        )""")
    # Điền dữ liệu trước khi trigger tồn tại, để không gì bị phát lại không cần thiết.
    op.execute(f"""
        INSERT INTO user_consents (user_id, purpose, data_group, granted, version, policy_version, changed_at)
        SELECT user_id, 'assistant', 'device', share_with_assistant, 1, '{POLICY_VERSION}',
               COALESCE(consented_at, updated_at)
        FROM health_connections
        ON CONFLICT (user_id, purpose, data_group) DO NOTHING""")
    op.execute("""
        INSERT INTO consent_events (user_id, purpose, data_group, granted, version, policy_version, actor, occurred_at)
        SELECT user_id, purpose, data_group, granted, version, policy_version, 'MIGRATION', changed_at
        FROM user_consents""")
    for statement in installation_statements():
        op.execute(statement)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS kg_user_consent ON user_consents")
    op.execute("DROP FUNCTION IF EXISTS kg_capture_user_consent()")
    op.execute("DROP TABLE IF EXISTS domain_event_deliveries, domain_events, consent_events, user_consents")
    op.execute("DROP INDEX IF EXISTS uq_health_connections_health_user")
    op.execute("ALTER TABLE health_connections DROP CONSTRAINT IF EXISTS ck_health_connections_api_version")
    for column in ("api_version", "lease_epoch", "generation", "health_user_id"):
        op.execute(f"ALTER TABLE health_connections DROP COLUMN IF EXISTS {column}")
    # kg_device_consent quay về dùng share_with_assistant khi user_consents không còn.
