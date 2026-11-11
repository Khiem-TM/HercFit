-- Context Graph (text-to-Cypher): mẫu truy vấn đã học, cổng read-your-writes và đánh thức worker.

-- Mẫu Cypher theo vân tay (intent, focus, độ hạt thời gian, có từ khoá, phiên bản lược đồ). Chỉ lưu văn bản truy vấn
-- đã qua validator, không bao giờ lưu giá trị tham số (chủ sở hữu, ngày, từ khoá) hay câu hỏi của người dùng.
CREATE TABLE IF NOT EXISTS kg_query_templates (
    fingerprint text PRIMARY KEY,
    cypher text NOT NULL,
    schema_version integer NOT NULL,
    status text NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'trusted', 'quarantined')),
    hits integer NOT NULL DEFAULT 0,
    failures integer NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_kg_outbox_owner_pending
    ON kg_outbox (owner_id) WHERE delivered_at IS NULL;

-- Giống core/graph_outbox.py: database nào tạo phong bì outbox trước thì cài trigger này.
CREATE OR REPLACE FUNCTION kg_outbox_notify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('kg_outbox', '');
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS kg_outbox_notify ON kg_outbox;
CREATE TRIGGER kg_outbox_notify AFTER INSERT ON kg_outbox
    FOR EACH STATEMENT EXECUTE FUNCTION kg_outbox_notify();
