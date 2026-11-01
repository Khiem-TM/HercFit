"""Các route v1 đã có bản kế nhiệm v2 đầy đủ, khoá theo mẫu route.

Phản hồi trên các route này có `Deprecation: true` và header `Link: <successor>;
rel="successor-version"` (core.route_metrics). Một route chỉ bị gỡ sau khi
`python -m workers metrics` báo nó không có lưu lượng trong 30 ngày. Route chưa có
bản kế nhiệm đầy đủ (tổng hợp ngày, overview, hồ sơ sức khoẻ, thẻ trợ lý v1)
không được liệt kê và vẫn được hỗ trợ.
"""

SUPERSEDED_V1: dict[str, str] = {
    "/api/integrations/google-health/sync": "/api/v2/integrations/google-health/sync-jobs",
    "/api/health/sleep": "/api/v2/health/sessions?kind=sleep",
    "/api/health/workouts": "/api/v2/health/sessions?kind=workout",
    "/api/health/samples": "/api/v2/health/series",
}
REMOVAL_QUIET_DAYS = 30
