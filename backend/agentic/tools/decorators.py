"""Tool execution decorators for latency measurement, payload logging, retry, and error wrapping."""

import asyncio
from functools import wraps
import inspect
import logging
import time
from typing import Any, Callable

from core.exceptions import ToolCallError

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {"auth_token", "token", "password", "secret", "api_key", "authorization"}


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for k, v in payload.items():
        if k.lower() in _SENSITIVE_KEYS and v:
            sanitized[k] = "***REDACTED***"
        else:
            sanitized[k] = v
    return sanitized


def tool_monitor(
    *,
    name: str | None = None,
    max_retries: int = 1,
    retry_delay: float = 0.15,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap sync or async tool functions with latency logging, retries, and ToolCallError normalization."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or func.__name__

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                safe_kwargs = _sanitize_payload(kwargs)
                last_exc: Exception | None = None
                for attempt in range(1, max_retries + 1):
                    start_ts = time.perf_counter()
                    try:
                        result = await func(*args, **kwargs)
                        elapsed_ms = (time.perf_counter() - start_ts) * 1000
                        logger.info(
                            "Tool '%s' succeeded in %.2fms (attempt=%d, args=%s)",
                            tool_name,
                            elapsed_ms,
                            attempt,
                            safe_kwargs,
                        )
                        return result
                    except ToolCallError:
                        raise
                    except Exception as exc:
                        last_exc = exc
                        elapsed_ms = (time.perf_counter() - start_ts) * 1000
                        logger.warning(
                            "Tool '%s' failed in %.2fms (attempt=%d/%d): %s",
                            tool_name,
                            elapsed_ms,
                            attempt,
                            max_retries,
                            exc,
                        )
                        if attempt < max_retries:
                            await asyncio.sleep(retry_delay * attempt)
                raise ToolCallError(
                    f"Tool '{tool_name}' failed after {max_retries} attempt(s): {last_exc}",
                    tool_name=tool_name,
                    payload=safe_kwargs,
                ) from last_exc

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            safe_kwargs = _sanitize_payload(kwargs)
            last_exc: Exception | None = None
            for attempt in range(1, max_retries + 1):
                start_ts = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    elapsed_ms = (time.perf_counter() - start_ts) * 1000
                    logger.info(
                        "Tool '%s' succeeded in %.2fms (attempt=%d, args=%s)",
                        tool_name,
                        elapsed_ms,
                        attempt,
                        safe_kwargs,
                    )
                    return result
                except ToolCallError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    elapsed_ms = (time.perf_counter() - start_ts) * 1000
                    logger.warning(
                        "Tool '%s' failed in %.2fms (attempt=%d/%d): %s",
                        tool_name,
                        elapsed_ms,
                        attempt,
                        max_retries,
                        exc,
                    )
                    if attempt < max_retries:
                        time.sleep(retry_delay * attempt)
            raise ToolCallError(
                f"Tool '{tool_name}' failed after {max_retries} attempt(s): {last_exc}",
                tool_name=tool_name,
                payload=safe_kwargs,
            ) from last_exc

        return sync_wrapper

    return decorator

