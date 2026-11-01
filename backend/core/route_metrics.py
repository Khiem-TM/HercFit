"""Số request và histogram độ trễ theo route, tổng hợp trong bộ nhớ, ghi xuống PostgreSQL.

Lý do: một route /api (v1) đã bị thay thế chỉ được gỡ khi không có lưu lượng trong 30 ngày,
và các SLO của API (ack webhook p95 < 2 s, context API p95 < 500 ms) cần độ trễ theo
route. Nhãn là *mẫu* route (không bao giờ là đường dẫn cụ thể), method, phiên bản
API và loại client, nên không ghi lại định danh, token hay giá trị sức khoẻ nào.

Mỗi tiến trình giữ bộ đếm riêng và cộng vào `api_route_usage` mỗi phút một lần
(và khi tắt); nhờ vậy nhiều tiến trình API vẫn cộng đúng. Lần ghi thất bại đặt
số đếm trở lại cho lần thử sau. Việc ghi nhận không bao giờ làm hỏng request.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import suppress
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text

logger = logging.getLogger(__name__)
# Các cận trên (ms); thêm một bucket đếm mọi request chậm hơn.
BUCKETS_MS = (25, 50, 100, 250, 500, 1000, 2000, 5000)
FLUSH_SECONDS = 60
UNMATCHED = "<unmatched>"
# Các route không đưa vào tài liệu OpenAPI vẫn cần nhãn.
HIDDEN_TEMPLATES = ("/api/v2/integrations/google-health/webhooks/{subscriber}",
                    "/api/integrations/google-health/callback", "/api/login", "/api/logout")

UPSERT = text("""
    INSERT INTO api_route_usage (day, api, method, route, client, requests, errors, latency_ms_sum, latency_buckets)
    VALUES (:day, :api, :method, :route, :client, :requests, :errors, :latency, CAST(:buckets AS bigint[]))
    ON CONFLICT (day, api, method, route, client) DO UPDATE SET
        requests = api_route_usage.requests + EXCLUDED.requests,
        errors = api_route_usage.errors + EXCLUDED.errors,
        latency_ms_sum = api_route_usage.latency_ms_sum + EXCLUDED.latency_ms_sum,
        latency_buckets = ARRAY(SELECT a + b FROM unnest(api_route_usage.latency_buckets, EXCLUDED.latency_buckets)
                                WITH ORDINALITY AS t(a, b, i) ORDER BY i),
        last_seen_at = now()""")


def bucket(elapsed_ms: float) -> int:
    for index, bound in enumerate(BUCKETS_MS):
        if elapsed_ms <= bound:
            return index
    return len(BUCKETS_MS)


def percentile(buckets: list[int], q: float) -> float | None:
    """Cận trên của bucket chứa phân vị q (None khi không có request, inf khi vượt cận cuối)."""
    total = sum(buckets)
    if not total:
        return None
    rank, seen = q * total, 0
    for index, count in enumerate(buckets):
        seen += count
        if seen >= rank:
            return float(BUCKETS_MS[index]) if index < len(BUCKETS_MS) else float("inf")
    return float("inf")


def _pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", template)
    regex = "".join((".+" if part.endswith(":path}") else "[^/]+") if part.startswith("{") else re.escape(part)
                    for part in parts if part)
    return re.compile(f"^{regex}$")


class RouteTable:
    """Đường dẫn cụ thể -> mẫu route; mẫu có nhiều phần chữ cố định hơn được ưu tiên (/{kind}:preview trước /{kind})."""

    def __init__(self, templates: list[str] | tuple[str, ...]):
        ordered = sorted(set(templates), key=lambda item: (-len(re.sub(r"\{[^}]+\}", "", item)), item))
        self._routes = [(_pattern(item), item) for item in ordered]

    def resolve(self, path: str) -> str:
        for pattern, template in self._routes:
            if pattern.match(path):
                return template
        return UNMATCHED


class RouteMetrics:
    def __init__(self) -> None:
        self._data: dict[tuple[date, str, str, str, str], list[Any]] = {}

    def record(self, *, api: str, method: str, route: str, client: str, status: int, elapsed_ms: float,
               day: date | None = None) -> None:
        key = (day or datetime.now(timezone.utc).date(), api, method, route, client)
        entry = self._data.get(key)
        if entry is None:
            entry = self._data[key] = [0, 0, 0.0, [0] * (len(BUCKETS_MS) + 1)]
        entry[0] += 1
        entry[1] += status >= 500
        entry[2] += elapsed_ms
        entry[3][bucket(elapsed_ms)] += 1

    def drain(self) -> dict[tuple[date, str, str, str, str], list[Any]]:
        data, self._data = self._data, {}
        return data

    def _restore(self, data: dict) -> None:
        for key, (requests, errors, latency, buckets) in data.items():
            entry = self._data.setdefault(key, [0, 0, 0.0, [0] * (len(BUCKETS_MS) + 1)])
            entry[0] += requests
            entry[1] += errors
            entry[2] += latency
            entry[3] = [a + b for a, b in zip(entry[3], buckets)]

    async def flush(self, session_scope: Callable[[], Any]) -> int:
        data = self.drain()
        if not data:
            return 0
        try:
            async with session_scope() as session:
                for (day, api, method, route, client), (requests, errors, latency, buckets) in data.items():
                    await session.execute(UPSERT, {"day": day, "api": api, "method": method, "route": route,
                                                   "client": client, "requests": requests, "errors": errors,
                                                   "latency": latency, "buckets": buckets})
        except Exception:
            self._restore(data)
            raise
        return len(data)


ROUTE_METRICS = RouteMetrics()


def _client(headers: list[tuple[bytes, bytes]]) -> str:
    values = dict(headers)
    if values.get(b"x-hercfit-client", b"").lower() == b"agent":
        return "agent"
    return "user" if values.get(b"authorization") else "anonymous"


class RouteMetricsMiddleware:
    """ASGI thuần: đếm request /api theo mẫu; thêm header Deprecation/Link cho các route v1 đã bị thay thế."""

    def __init__(self, app, metrics: RouteMetrics | None = None, superseded: dict[str, str] | None = None,
                 extra_templates: tuple[str, ...] = HIDDEN_TEMPLATES):
        self.app = app
        self.metrics = metrics or ROUTE_METRICS
        self.superseded = superseded if superseded is not None else _superseded()
        self.extra = extra_templates
        self._table: RouteTable | None = None

    def table(self, scope) -> RouteTable:
        if self._table is None:
            application = scope.get("app")
            paths = list(application.openapi().get("paths", {})) if hasattr(application, "openapi") else []
            self._table = RouteTable([path for path in paths if path.startswith("/api/")] + list(self.extra))
        return self._table

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith("/api/") or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        try:
            route = self.table(scope).resolve(path)
        except Exception:  # noqa: BLE001 - đo lường không bao giờ làm hỏng request
            route = UNMATCHED
        successor = self.superseded.get(route)
        status = {"code": 500}

        async def capture(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                if successor:
                    message = {**message, "headers": [*message.get("headers", []), (b"deprecation", b"true"),
                                                      (b"link", f'<{successor}>; rel="successor-version"'.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            with suppress(Exception):
                self.metrics.record(api="v2" if path.startswith("/api/v2/") else "v1", method=scope["method"],
                                    route=route, client=_client(scope.get("headers") or []), status=status["code"],
                                    elapsed_ms=(time.perf_counter() - started) * 1000)


def _superseded() -> dict[str, str]:
    from api.deprecations import SUPERSEDED_V1
    return SUPERSEDED_V1


async def flush_loop(stop: asyncio.Event, session_scope: Callable[[], Any],
                     metrics: RouteMetrics | None = None, every: float = FLUSH_SECONDS) -> None:
    metrics = metrics or ROUTE_METRICS
    while True:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), every)
        try:
            await metrics.flush(session_scope)
        except Exception as exc:  # noqa: BLE001 - giữ trong bộ nhớ, thử lại phút sau
            logger.warning("route_metrics_flush_failed error=%s", type(exc).__name__)
        if stop.is_set():
            return


__all__ = ["BUCKETS_MS", "ROUTE_METRICS", "RouteMetrics", "RouteMetricsMiddleware", "RouteTable", "flush_loop",
           "percentile"]
