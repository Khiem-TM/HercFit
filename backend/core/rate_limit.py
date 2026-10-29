"""Small in-process sliding-window limiter.

It protects one process from bursts (credential stuffing, refresh loops). Several
replicas each keep their own window, so put a gateway limit in front of a
multi-replica deployment as well. Behind a reverse proxy, run uvicorn with
--proxy-headers and --forwarded-allow-ips so request.client is the real client.
"""
from collections import deque
from time import monotonic

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 10_000):
        self.limit, self.window, self.max_keys = limit, window_seconds, max_keys
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]

    def check(self, key: str, now: float | None = None) -> float | None:
        """Record a hit; return seconds to wait when the key is over its limit."""
        if self.limit <= 0:
            return None
        now = monotonic() if now is None else now
        if len(self._hits) >= self.max_keys:
            self._prune(now)
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(0.0, hits[0] + self.window - now)
        hits.append(now)
        return None


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce(limiter: SlidingWindowLimiter, key: str, detail: str = "Quá nhiều yêu cầu, vui lòng thử lại sau.") -> None:
    wait = limiter.check(key)
    if wait is not None:
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(max(1, int(wait) + 1))})
