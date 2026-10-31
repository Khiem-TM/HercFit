"""Thin async client for health.googleapis.com/v4.

Provider bodies may echo request details, so only status codes and error classes
are logged. Retries cover 429 and 5xx with Retry-After or exponential backoff.
"""
import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)
BASE_URL = "https://health.googleapis.com/v4"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
MAX_ATTEMPTS = 3
MAX_PAGES = 50
# Page size caps documented per data type; sessions are limited to 25.
SESSION_TYPES = {"sleep", "exercise"}


class GoogleHealthError(Exception):
    """A provider call failed; `code` is a short, loggable classification."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class ReauthRequired(GoogleHealthError):
    def __init__(self, status: int | None = None):
        super().__init__("reauth_required", status)


def error_reason(response: httpx.Response) -> str | None:
    """Google's machine-readable reason (e.g. SERVICE_DISABLED), never the free-text message."""
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        return None
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            return str(detail["reason"])[:64]
    status = error.get("status")
    return str(status)[:64] if status else None


def civil_date(day: date) -> dict[str, Any]:
    return {"date": {"year": day.year, "month": day.month, "day": day.day}, "time": {}}


def field_path(data_type: str) -> str:
    """Filters use snake_case field paths; the URL uses kebab-case type ids."""
    return data_type.replace("-", "_")


class GoogleHealthClient:
    def __init__(self, access_token: str, http: httpx.AsyncClient, *,
                 sleep: Callable[[float], Any] = asyncio.sleep, base_url: str = BASE_URL):
        self._headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        self._http = http
        self._sleep = sleep
        self._base = base_url.rstrip("/")

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       body: dict | None = None) -> dict[str, Any]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await self._http.request(method, f"{self._base}/{path}", params=params, json=body,
                                                     headers=self._headers, timeout=TIMEOUT)
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS:
                    logger.warning("google_health_network_error path=%s error=%s", path.split("/")[-1], type(exc).__name__)
                    raise GoogleHealthError("network") from None
                await self._sleep(2 ** (attempt - 1))
                continue
            if response.status_code == 200:
                return response.json()
            if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
                retry_after = response.headers.get("retry-after", "")
                await self._sleep(min(10.0, float(retry_after)) if retry_after.isdigit() else 2 ** (attempt - 1))
                continue
            reason = error_reason(response)
            logger.warning("google_health_http_error path=%s status=%s reason=%s", path.split("/")[-1],
                           response.status_code, reason)
            if response.status_code == 401:
                raise ReauthRequired(401)
            code = {403: "forbidden", 404: "unavailable", 429: "rate_limited"}.get(response.status_code, "provider_error")
            raise GoogleHealthError(f"{code}:{reason}" if reason else code, response.status_code)
        raise GoogleHealthError("provider_error")

    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", "users/me/profile")

    async def get_settings(self) -> dict[str, Any]:
        return await self._request("GET", "users/me/settings")

    async def list_points(self, data_type: str, *, filter: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pageSize": 25 if data_type in SESSION_TYPES else 1000}
        if filter:
            params["filter"] = filter
        points: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            page = await self._request("GET", f"users/me/dataTypes/{data_type}/dataPoints", params=params)
            points.extend(page.get("dataPoints") or [])
            token = page.get("nextPageToken")
            if not token:
                return points
            params["pageToken"] = token
        logger.warning("google_health_page_limit type=%s", data_type)
        return points

    async def daily_rollup(self, data_type: str, start: date, end_exclusive: date) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"range": {"start": civil_date(start), "end": civil_date(end_exclusive)},
                                "windowSizeDays": 1, "pageSize": 1000}
        points: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            page = await self._request("POST", f"users/me/dataTypes/{data_type}/dataPoints:dailyRollUp", body=body)
            points.extend(page.get("rollupDataPoints") or [])
            token = page.get("nextPageToken")
            if not token:
                return points
            body["pageToken"] = token
        return points
