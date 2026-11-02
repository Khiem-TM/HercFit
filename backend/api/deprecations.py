"""Các route v1 đã có bản kế nhiệm v2 đầy đủ, khoá theo mẫu route.

Phản hồi trên các route này có `Deprecation: true` và header `Link: <successor>;
rel="successor-version"` (core.route_metrics). Hiện không có route nào bị thay thế: các route
/api/health/* và /api/integrations/google-health là đường chính của bản tích hợp Google Health
theo reconcile.
"""

SUPERSEDED_V1: dict[str, str] = {}
REMOVAL_QUIET_DAYS = 30
