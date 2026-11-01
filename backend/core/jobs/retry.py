"""Điều gì xảy ra sau khi một job thất bại, theo lớp lỗi.

TRANSIENT   mạng, 5xx, mất lease: thử lại với backoff full-jitter (5 s .. 30 phút)
RATE_LIMIT  429 hoặc quota cục bộ: thử lại sau Retry-After (hoặc backoff)
PERMISSION  thiếu hoặc bị thu hồi scope: dừng, không thử lại, cursor giữ nguyên (NOT_GRANTED)
REAUTH      refresh token đã chết: kết nối NEEDS_REAUTH, các job của nó tạm dừng
SCHEMA      request hoặc payload bị từ chối: cần sửa code hoặc hợp đồng
UNSUPPORTED loại hoặc tài nguyên không có cho người dùng hay phiên bản này
BUG         exception bất ngờ: thử lại, rồi chuyển sang cần xử lý
Job dùng hết max_attempts chuyển sang NEEDS_ATTENTION.
"""
from __future__ import annotations

import random
from datetime import timedelta

BASE_SECONDS = 5.0
CAP_SECONDS = 30 * 60.0
RETRYABLE = frozenset({"TRANSIENT", "RATE_LIMIT", "BUG", "PROVIDER"})


def backoff(attempt: int, *, jitter=random.uniform) -> timedelta:
    return timedelta(seconds=jitter(BASE_SECONDS, min(CAP_SECONDS, BASE_SECONDS * 2 ** max(0, attempt - 1))))


def decide(error_class: str, attempt: int, max_attempts: int, retry_after: float | None = None, *,
           jitter=random.uniform) -> tuple[str, timedelta | None]:
    """("RETRY", delay) hoặc ("NEEDS_ATTENTION", None) hoặc ("STOP", None)."""
    if error_class in ("PERMISSION", "UNSUPPORTED"):
        return "STOP", None
    if error_class in ("REAUTH", "SCHEMA"):
        return "NEEDS_ATTENTION", None
    if error_class in RETRYABLE and attempt < max_attempts:
        if error_class == "RATE_LIMIT" and retry_after is not None:
            return "RETRY", timedelta(seconds=min(CAP_SECONDS, max(1.0, retry_after)))
        return "RETRY", backoff(attempt, jitter=jitter)
    return "NEEDS_ATTENTION", None
