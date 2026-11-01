"""Operational metrics for the health platform, computed from PostgreSQL (no extra infrastructure).

    python -m workers metrics

queue age per kind, jobs by state, per-type sync lag, retries, needs-attention,
export states (UNCERTAIN / CONFLICT / BLOCKED), webhook backlog, knowledge-graph
outbox lag, superseded /api (v1) route traffic and the SLOs:
  webhook ack p95 < 2 s, data available p95 < 5 min, context API p95 < 500 ms.
Values are counts and durations only: never tokens or health values.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from api.deprecations import REMOVAL_QUIET_DAYS, SUPERSEDED_V1
from core.database import get_db_session
from core.route_metrics import BUCKETS_MS, percentile

WEBHOOK_ROUTE = "/api/v2/integrations/google-health/webhooks/{subscriber}"
CONTEXT_ROUTES = ("/api/v2/assistant/context", "/api/v2/assistant/context:query")
SLO_TARGETS = {"webhook_ack_p95_ms": 2000, "data_available_p95_s": 300, "context_api_p95_ms": 500}

QUERIES = {
    "queue_age_seconds": """
        SELECT kind, count(*) AS ready, COALESCE(EXTRACT(EPOCH FROM now() - min(run_after)), 0)::int AS oldest_s
        FROM jobs WHERE state IN ('QUEUED', 'RETRY') AND run_after <= now() GROUP BY kind ORDER BY kind""",
    "jobs_by_state": "SELECT state, count(*) AS n FROM jobs GROUP BY state ORDER BY state",
    "retrying": """
        SELECT kind, error_class, count(*) AS n FROM jobs WHERE state = 'RETRY' GROUP BY kind, error_class
        ORDER BY n DESC""",
    "needs_attention": """
        SELECT kind, error_class, error_code, count(*) AS n FROM jobs WHERE state = 'NEEDS_ATTENTION'
        GROUP BY kind, error_class, error_code ORDER BY n DESC LIMIT 20""",
    "sync_lag_days": """
        SELECT data_type, count(*) AS connections,
               max(CURRENT_DATE - complete_through) AS worst_days, min(CURRENT_DATE - complete_through) AS best_days,
               count(*) FILTER (WHERE status <> 'COMPLETE') AS not_complete
        FROM sync_cursors GROUP BY data_type ORDER BY worst_days DESC NULLS FIRST""",
    "export_states": "SELECT state, count(*) AS n FROM export_outbox GROUP BY state ORDER BY state",
    "open_conflicts": "SELECT count(*) AS n FROM export_conflicts WHERE resolution IS NULL",
    "webhook_backlog": """
        SELECT state, count(*) AS n, COALESCE(EXTRACT(EPOCH FROM now() - min(received_at)), 0)::int AS oldest_s
        FROM webhook_inbox WHERE received_at > now() - interval '7 days' GROUP BY state""",
    "webhook_to_data_p95_seconds": """
        SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM j.finished_at - w.received_at)) AS p95
        FROM webhook_inbox w JOIN jobs j ON j.id = w.job_id
        WHERE j.finished_at IS NOT NULL AND w.received_at > now() - interval '1 day'""",
    "connections": "SELECT status, count(*) AS n FROM health_connections GROUP BY status",
    "graph_outbox_lag_seconds": """
        SELECT count(*) AS pending, COALESCE(EXTRACT(EPOCH FROM now() - min(occurred_at)), 0)::int AS oldest_s
        FROM kg_outbox WHERE delivered_at IS NULL""",
}


async def collect() -> dict[str, Any]:
    result: dict[str, Any] = {}
    async with get_db_session() as session:
        for name, sql in QUERIES.items():
            try:
                async with session.begin_nested():
                    rows = (await session.execute(text(sql))).mappings().all()
            except Exception as exc:  # a table may not exist on an older schema
                result[name] = {"error": type(exc).__name__}
                continue
            result[name] = [{key: (float(value) if hasattr(value, "is_finite") else value) for key, value in row.items()}
                            for row in rows]
        try:
            async with session.begin_nested():
                result["legacy_routes"] = await legacy_routes(session)
                result["slo"] = await slo(session, result.get("webhook_to_data_p95_seconds"))
        except Exception as exc:  # api_route_usage arrives with migration 0022
            result["legacy_routes"] = result["slo"] = {"error": type(exc).__name__}
    return result


async def _buckets(session, routes: tuple[str, ...], since: date, method: str | None = None) -> list[int]:
    rows = (await session.execute(text("""
        SELECT latency_buckets FROM api_route_usage WHERE route = ANY(:routes) AND day >= :since
          AND (CAST(:method AS text) IS NULL OR method = :method)"""),
        {"routes": list(routes), "since": since, "method": method})).scalars().all()
    total = [0] * (len(BUCKETS_MS) + 1)
    for buckets in rows:
        total = [a + b for a, b in zip(total, buckets)]
    return total


async def legacy_routes(session, today: date | None = None) -> dict[str, Any]:
    """Superseded v1 routes: traffic over the quiet window and whether removal is allowed yet."""
    today = today or date.today()
    since = today - timedelta(days=REMOVAL_QUIET_DAYS)
    first = (await session.execute(text("SELECT min(day) FROM api_route_usage"))).scalar_one_or_none()
    observed_long_enough = first is not None and first <= since
    rows = {row.route: row for row in (await session.execute(text("""
        SELECT route, sum(requests) AS requests, max(day) AS last_day,
               sum(requests) FILTER (WHERE client = 'agent') AS agent_requests
        FROM api_route_usage WHERE route = ANY(:routes) AND day >= :since GROUP BY route"""),
        {"routes": list(SUPERSEDED_V1), "since": since})).all()}
    routes = []
    for route, successor in SUPERSEDED_V1.items():
        row = rows.get(route)
        requests = int(row.requests) if row else 0
        routes.append({"route": route, "successor": successor, "requests_30d": requests,
                       "agent_requests_30d": int(row.agent_requests or 0) if row else 0,
                       "last_day": row.last_day.isoformat() if row else None,
                       "removable": observed_long_enough and requests == 0})
    return {"observed_since": first.isoformat() if first else None, "quiet_days_required": REMOVAL_QUIET_DAYS,
            "routes": routes}


async def slo(session, data_available: Any = None, today: date | None = None) -> dict[str, Any]:
    since = (today or date.today()) - timedelta(days=7)
    webhook = percentile(await _buckets(session, (WEBHOOK_ROUTE,), since, "POST"), 0.95)
    context = percentile(await _buckets(session, CONTEXT_ROUTES, since, "GET"), 0.95)
    available = (data_available or [{}])[0].get("p95") if isinstance(data_available, list) else None
    values = {"webhook_ack_p95_ms": webhook, "data_available_p95_s": available, "context_api_p95_ms": context}
    return {name: {"value": value if value != float("inf") else f">{BUCKETS_MS[-1]}", "target": SLO_TARGETS[name],
                   "ok": None if value is None else value <= SLO_TARGETS[name],
                   "method": "7-day histogram upper bound" if name.endswith("_ms") else "1-day percentile"}
            for name, value in values.items()}
