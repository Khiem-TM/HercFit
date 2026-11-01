"""v1 routes that have a complete v2 successor, keyed by route template.

Responses on these routes carry `Deprecation: true` and a `Link: <successor>;
rel="successor-version"` header (core.route_metrics). A route is removed only after
`python -m workers metrics` reports it with no traffic for 30 days. Routes without a
complete successor (daily summaries, overview, health profile, the v1 assistant card)
are not listed and stay supported.
"""

SUPERSEDED_V1: dict[str, str] = {
    "/api/integrations/google-health/sync": "/api/v2/integrations/google-health/sync-jobs",
    "/api/health/sleep": "/api/v2/health/sessions?kind=sleep",
    "/api/health/workouts": "/api/v2/health/sessions?kind=workout",
    "/api/health/samples": "/api/v2/health/series",
}
REMOVAL_QUIET_DAYS = 30
