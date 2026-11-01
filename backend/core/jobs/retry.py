"""What happens after a job fails, by error class.

TRANSIENT   network, 5xx, lost lease: retry with full-jitter backoff (5 s .. 30 min)
RATE_LIMIT  429 or local quota: retry after Retry-After (or backoff)
PERMISSION  scope missing or revoked: stop, no retry, cursor stays (NOT_GRANTED)
REAUTH      refresh token dead: connection NEEDS_REAUTH, its jobs pause
SCHEMA      request or payload rejected: needs a code or contract fix
UNSUPPORTED type or resource not available for this user or version
BUG         unexpected exception: retried, then needs attention
A job that exhausts max_attempts goes to NEEDS_ATTENTION.
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
    """("RETRY", delay) or ("NEEDS_ATTENTION", None) or ("STOP", None)."""
    if error_class in ("PERMISSION", "UNSUPPORTED"):
        return "STOP", None
    if error_class in ("REAUTH", "SCHEMA"):
        return "NEEDS_ATTENTION", None
    if error_class in RETRYABLE and attempt < max_attempts:
        if error_class == "RATE_LIMIT" and retry_after is not None:
            return "RETRY", timedelta(seconds=min(CAP_SECONDS, max(1.0, retry_after)))
        return "RETRY", backoff(attempt, jitter=jitter)
    return "NEEDS_ATTENTION", None
