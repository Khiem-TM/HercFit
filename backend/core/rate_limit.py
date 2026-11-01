"""Bộ giới hạn cửa sổ trượt nhỏ trong tiến trình.

Nó bảo vệ một tiến trình khỏi các đợt dồn dập (dò mật khẩu hàng loạt, vòng lặp refresh). Nhiều
bản sao thì mỗi bản giữ cửa sổ riêng, nên với triển khai nhiều bản sao hãy đặt thêm
giới hạn ở gateway phía trước. Sau reverse proxy, chạy uvicorn với
--proxy-headers và --forwarded-allow-ips để request.client là client thật.
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
        """Ghi nhận một lượt; trả về số giây phải chờ khi khoá vượt giới hạn."""
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
