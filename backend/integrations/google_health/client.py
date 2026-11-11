"""Client bất đồng bộ cho health.googleapis.com v4.

* Đọc: `list`, `reconcile` (luồng gộp mọi nguồn, đã khử trùng lặp; `family` chọn họ nguồn,
  ví dụ self-sources = chỉ điểm do OAuth client này ghi) và `dailyRollUp`.
  Phân trang không bao giờ âm thầm cắt bớt: các hàm `*_all` trả về `Fetch(points, complete,
  next_token)`; hết ngân sách trang thì `complete=False`, bên gọi không được coi là đủ cửa sổ.
* Ghi: create / patch / batchDelete, mỗi lệnh trả về một google.longrunning Operation.
  Google tự cấp id nên create không bao giờ được thử lại.
* Lỗi mang `error_class` quyết định bước tiếp theo:
  TRANSIENT (thử lại sau), RATE_LIMIT, PERMISSION (thiếu hoặc bị thu hồi scope), REAUTH (refresh
  token đã chết), SCHEMA (request bị từ chối: cần sửa code), UNSUPPORTED, PROVIDER (các 4xx khác).
* Thử lại áp dụng cho 429/5xx/lỗi mạng với backoff mũ full-jitter.

Body phản hồi của nhà cung cấp có thể lặp lại chi tiết request, nên chỉ ghi log
mã trạng thái và lý do dạng máy.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)
ROOT_URL = "https://health.googleapis.com"
BASE_URL = f"{ROOT_URL}/v4"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
MAX_ATTEMPTS = 4
BACKOFF_BASE = 1.0
BACKOFF_CAP = 20.0
RETRY_STATUSES = {429, 500, 502, 503, 504}

TRANSIENT, RATE_LIMIT, PERMISSION, REAUTH, SCHEMA, UNSUPPORTED, PROVIDER = (
    "TRANSIENT", "RATE_LIMIT", "PERMISSION", "REAUTH", "SCHEMA", "UNSUPPORTED", "PROVIDER")


class GoogleHealthError(Exception):
    """Một lời gọi nhà cung cấp thất bại; `code` là lý do ngắn ghi log được, `error_class` điều khiển việc thử lại."""

    def __init__(self, code: str, status: int | None = None, error_class: str = PROVIDER,
                 retry_after: float | None = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.error_class = error_class
        self.retry_after = retry_after


class ReauthRequired(GoogleHealthError):
    def __init__(self, status: int | None = None):
        super().__init__("reauth_required", status, REAUTH)


@dataclass
class Page:
    points: list[dict[str, Any]]
    next_token: str | None


@dataclass
class Fetch:
    points: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True
    next_token: str | None = None
    pages: int = 0


def error_reason(response: httpx.Response) -> str | None:
    """Lý do dạng máy của Google (ví dụ SERVICE_DISABLED), không bao giờ là thông điệp văn bản tự do."""
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        return None
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("reason"):
            return str(detail["reason"])[:64]
    status = error.get("status")
    return str(status)[:64] if status else None


def classify(status: int, reason: str | None) -> tuple[str, str]:
    """(code, error_class) cho phản hồi cuối không phải 2xx."""
    if status == 400:
        return "invalid_request", SCHEMA
    if status == 403:
        if reason in ("SERVICE_DISABLED", "API_DISABLED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"):
            return "forbidden", PERMISSION if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT" else PROVIDER
        return "forbidden", PERMISSION
    if status == 404:
        return "unavailable", UNSUPPORTED
    if status == 409:
        return "already_exists", PROVIDER
    if status == 429:
        return "rate_limited", RATE_LIMIT
    if status >= 500:
        return "provider_error", TRANSIENT
    return "provider_error", PROVIDER


def civil_date(day: date) -> dict[str, Any]:
    return {"date": {"year": day.year, "month": day.month, "day": day.day}}


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def field_path(data_type: str) -> str:
    """Filter dùng đường dẫn trường snake_case; URL dùng id loại dạng kebab-case."""
    return data_type.replace("-", "_")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "")
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class GoogleHealthClient:
    def __init__(self, access_token: str, http: httpx.AsyncClient, *,
                 sleep: Callable[[float], Any] = asyncio.sleep, base_url: str | None = None,
                 jitter: Callable[[float, float], float] = random.uniform):
        from core.settings import settings

        self._headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        self._http = http
        self._sleep = sleep
        # GOOGLE_HEALTH_API_ROOT trỏ test hoặc emulator tới nơi khác (https, hoặc http chỉ trên localhost).
        self._root = settings.GOOGLE_HEALTH_API_ROOT.rstrip("/")
        self._base = (base_url or f"{self._root}/v4").rstrip("/")
        self._jitter = jitter

    def _backoff(self, attempt: int) -> float:
        return self._jitter(0, min(BACKOFF_CAP, BACKOFF_BASE * 2 ** (attempt - 1)))

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       body: dict | None = None, retry: bool = True) -> Any:
        """`retry=False` cho lệnh ghi không idempotent: kết quả chưa rõ được báo lên, không bao giờ gửi lại."""
        label = path.split("/")[-1].split(":")[-1]
        attempts = MAX_ATTEMPTS if retry else 1
        for attempt in range(1, attempts + 1):
            try:
                response = await self._http.request(method, f"{self._base}/{path}", params=params, json=body,
                                                     headers=self._headers, timeout=TIMEOUT)
            except httpx.HTTPError as exc:
                if attempt == attempts:
                    logger.warning("google_health_network_error path=%s error=%s", label, type(exc).__name__)
                    raise GoogleHealthError("network", None, TRANSIENT) from None
                await self._sleep(self._backoff(attempt))
                continue
            if response.status_code == 200:
                return response.json() if response.content else {}
            if response.status_code in RETRY_STATUSES and attempt < attempts:
                wait = _retry_after(response)
                await self._sleep(min(BACKOFF_CAP, wait) if wait is not None else self._backoff(attempt))
                continue
            reason = error_reason(response)
            logger.warning("google_health_http_error path=%s status=%s reason=%s", label, response.status_code, reason)
            if response.status_code == 401:
                raise ReauthRequired(401)
            code, error_class = classify(response.status_code, reason)
            raise GoogleHealthError(f"{code}:{reason}" if reason else code, response.status_code, error_class,
                                    _retry_after(response))
        raise GoogleHealthError("provider_error", None, TRANSIENT)

    # -- tài nguyên người dùng ------------------------------------------------------------------
    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", "users/me/profile")

    async def get_settings(self) -> dict[str, Any]:
        return await self._request("GET", "users/me/settings")

    # -- data point -------------------------------------------------------------------------------
    async def list_page(self, data_type: str, *, filter: str | None = None, page_size: int = 1000,
                        page_token: str | None = None, reconcile: bool = False, family: str | None = None) -> Page:
        params: dict[str, Any] = {"pageSize": page_size}
        if filter:
            params["filter"] = filter
        if page_token:
            params["pageToken"] = page_token
        if family:
            params["dataSourceFamily"] = f"users/me/dataSourceFamilies/{family}"
        suffix = ":reconcile" if reconcile else ""
        page = await self._request("GET", f"users/me/dataTypes/{data_type}/dataPoints{suffix}", params=params)
        return Page(page.get("dataPoints") or [], page.get("nextPageToken") or None)

    async def daily_rollup_page(self, data_type: str, start: date, end_exclusive: date, *, page_size: int = 90,
                                page_token: str | None = None) -> Page:
        body: dict[str, Any] = {"range": {"start": civil_date(start), "end": civil_date(end_exclusive)},
                                "windowSizeDays": 1, "pageSize": page_size}
        if page_token:
            body["pageToken"] = page_token
        page = await self._request("POST", f"users/me/dataTypes/{data_type}/dataPoints:dailyRollUp", body=body)
        return Page(page.get("rollupDataPoints") or [], page.get("nextPageToken") or None)

    async def rollup_page(self, data_type: str, start: datetime, end: datetime, *, window_seconds: int,
                          page_size: int = 1440, page_token: str | None = None) -> Page:
        """Gộp theo cửa sổ thời gian thực [start, end); cửa sổ không có dữ liệu không được trả về."""
        body: dict[str, Any] = {"range": {"startTime": _utc(start), "endTime": _utc(end)},
                                "windowSize": f"{window_seconds}s", "pageSize": page_size}
        if page_token:
            body["pageToken"] = page_token
        page = await self._request("POST", f"users/me/dataTypes/{data_type}/dataPoints:rollUp", body=body)
        return Page(page.get("rollupDataPoints") or [], page.get("nextPageToken") or None)

    async def rollup_all(self, data_type: str, start: datetime, end: datetime, *, window_seconds: int,
                         page_size: int = 1440, max_pages: int = 50) -> Fetch:
        result = Fetch()
        while result.pages < max_pages:
            page = await self.rollup_page(data_type, start, end, window_seconds=window_seconds, page_size=page_size,
                                          page_token=result.next_token)
            result.points.extend(page.points)
            result.pages += 1
            result.next_token = page.next_token
            if not page.next_token:
                return result
        result.complete = False
        logger.warning("google_health_page_budget type=%s pages=%s", data_type, result.pages)
        return result

    async def list_all(self, data_type: str, *, filter: str | None = None, page_size: int = 1000,
                       max_pages: int = 50, page_token: str | None = None, reconcile: bool = False,
                       family: str | None = None) -> Fetch:
        result = Fetch(next_token=page_token)
        while result.pages < max_pages:
            page = await self.list_page(data_type, filter=filter, page_size=page_size, page_token=result.next_token,
                                        reconcile=reconcile, family=family)
            result.points.extend(page.points)
            result.pages += 1
            result.next_token = page.next_token
            if not page.next_token:
                return result
        result.complete = False
        logger.warning("google_health_page_budget type=%s pages=%s", data_type, result.pages)
        return result

    async def daily_rollup_all(self, data_type: str, start: date, end_exclusive: date, *, page_size: int = 90,
                               max_pages: int = 50, page_token: str | None = None) -> Fetch:
        result = Fetch(next_token=page_token)
        while result.pages < max_pages:
            page = await self.daily_rollup_page(data_type, start, end_exclusive, page_size=page_size,
                                                page_token=result.next_token)
            result.points.extend(page.points)
            result.pages += 1
            result.next_token = page.next_token
            if not page.next_token:
                return result
        result.complete = False
        logger.warning("google_health_page_budget type=%s pages=%s", data_type, result.pages)
        return result

    # -- lệnh ghi (mỗi lệnh trả về một google.longrunning Operation) -----------------------------
    async def get_point(self, name: str) -> dict[str, Any]:
        return await self._request("GET", name)

    async def create_point(self, data_type: str, point: dict[str, Any]) -> dict[str, Any]:
        """Không bao giờ thử lại: Google tự cấp id, POST lần hai có thể thành data point thứ hai."""
        return await self._request("POST", f"users/me/dataTypes/{data_type}/dataPoints", body=point, retry=False)

    async def patch_point(self, name: str, point: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", name, body={**point, "name": name})

    async def batch_delete(self, data_type: str, names: list[str]) -> dict[str, Any]:
        return await self._request("POST", f"users/me/dataTypes/{data_type}/dataPoints:batchDelete",
                                   body={"names": names})
