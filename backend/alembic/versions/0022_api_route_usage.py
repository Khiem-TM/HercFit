"""Per-route API usage: request counts and latency histograms per day.

Rows are keyed by (day, api, method, route template, client kind). The route is the
template (/api/v2/health/logs/{kind}), never the concrete path, so no identifier or
health value is stored. Used to decide when a superseded /api (v1) route can be
removed (no traffic for 30 days) and to measure the API SLOs (webhook ack, context API).

latency_buckets counts requests per upper bound in core.route_metrics.BUCKETS_MS,
with one extra overflow bucket.
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
