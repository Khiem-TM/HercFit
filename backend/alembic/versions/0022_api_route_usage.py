"""Mức sử dụng API theo route: số request và histogram độ trễ theo ngày.

Các dòng có khoá (ngày, api, method, mẫu route, loại client). Route là
mẫu (/api/v2/health/logs/{kind}), không bao giờ là đường dẫn cụ thể, nên không lưu định danh
hay giá trị sức khoẻ nào. Dùng để quyết định khi nào một route /api (v1) đã bị thay thế có thể
gỡ (không có lưu lượng trong 30 ngày) và để đo SLO của API (ack webhook, context API).

latency_buckets đếm request theo từng cận trên trong core.route_metrics.BUCKETS_MS,
cộng thêm một bucket tràn.
"""
from alembic import op

revision = "0022_api_route_usage"
down_revision = "0021_health_export_analytics"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_route_usage (
            day date NOT NULL,
            api varchar(8) NOT NULL CHECK (api IN ('v1', 'v2')),
            method varchar(8) NOT NULL,
            route text NOT NULL,
            client varchar(16) NOT NULL CHECK (client IN ('user', 'agent', 'anonymous')),
            requests bigint NOT NULL DEFAULT 0,
            errors bigint NOT NULL DEFAULT 0,
            latency_ms_sum double precision NOT NULL DEFAULT 0,
            latency_buckets bigint[] NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (day, api, method, route, client)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_route_usage_route ON api_route_usage (route, day)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS api_route_usage")
