"""Async HTTP client base using httpx with retry, backoff, and request tracing."""

import asyncio
import logging
import time
from typing import Any
from uuid import uuid4

import httpx

from config.settings import agent_settings
from core.exceptions import BackendAPIError

logger = logging.getLogger(__name__)


class BaseHTTPClient:
    """Base asynchronous HTTP client with retry & trace ID propagation."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or agent_settings.BACKEND_BASE_URL).rstrip("/")
        self.timeout = (
            timeout if timeout is not None else agent_settings.BACKEND_TIMEOUT_SECONDS
        )
        self.max_retries = (
            max_retries if max_retries is not None else agent_settings.BACKEND_MAX_RETRIES
        )
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_headers(
        self,
        auth_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-Request-ID": trace_id or str(uuid4()),
        }
        if auth_token:
            token_val = (
                auth_token
                if auth_token.lower().startswith("bearer ")
                else f"Bearer {auth_token}"
            )
            headers["Authorization"] = token_val
        elif agent_settings.AUTH_SECRET:
            headers["Authorization"] = (
                f"Bearer {agent_settings.AUTH_SECRET.get_secret_value()}"
            )
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth_token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Execute an HTTP request with retry on transient errors (5xx / network timeout)."""
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        trace_id = str(uuid4())
        req_headers = self._build_headers(
            auth_token=auth_token, extra_headers=headers, trace_id=trace_id
        )
        client = await self.get_client()

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            start_ts = time.perf_counter()
            try:
                response = await client.request(
                    method=method.upper(),
                    url=path,
                    params=params,
                    json=json_body,
                    headers=req_headers,
                )
                elapsed_ms = (time.perf_counter() - start_ts) * 1000
                logger.debug(
                    "HTTP %s %s -> %s (%.1fms, trace_id=%s, attempt=%d)",
                    method.upper(),
                    path,
                    response.status_code,
                    elapsed_ms,
                    trace_id,
                    attempt,
                )
                if response.status_code >= 500 and attempt < self.max_retries:
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                    continue

                if response.status_code >= 400:
                    try:
                        body = response.json()
                    except Exception:
                        body = response.text
                    raise BackendAPIError(
                        f"Backend API returned HTTP {response.status_code} for {method.upper()} {path}",
                        endpoint=path,
                        status_code=response.status_code,
                        response_body=body,
                    )

                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()

            except BackendAPIError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
                last_exc = exc
                logger.warning(
                    "Transient HTTP error on %s %s (attempt %d/%d): %s",
                    method.upper(),
                    path,
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                    continue
                raise BackendAPIError(
                    f"Failed to connect to Backend API at {path}: {exc}",
                    endpoint=path,
                    status_code=503,
                ) from exc

        raise BackendAPIError(
            f"Exhausted retries calling {path}: {last_exc}",
            endpoint=path,
            status_code=503,
        )

