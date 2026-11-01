"""Service-to-service proof for the agent service (shared by backend and agentic).

The agent service signs each delegation request with a secret it shares with the
backend (AGENT_SERVICE_SECRET). The header is

    X-HercFit-Service: v1;<key id>;<unix ts>;<hex HMAC-SHA256>

over "v1\\n<ts>\\n<METHOD>\\n<path>\\n<user id>\\n<sha256(body)>". The key id lets
the backend pick the secret during a rotation; the timestamp bounds replay to a
short window, and a replay can only obtain a token for a user whose own access
token the caller already presents.
"""
from __future__ import annotations

import hashlib
import hmac
import time

HEADER = "X-HercFit-Service"
VERSION = "v1"
MAX_SKEW_SECONDS = 120


def key_id(secret: str) -> str:
    return hashlib.sha256(("hercfit-agent:" + secret).encode()).hexdigest()[:12]


def _message(ts: int, method: str, path: str, user_id: str, body: bytes) -> bytes:
    return "\n".join((VERSION, str(ts), method.upper(), path, user_id, hashlib.sha256(body).hexdigest())).encode()


def sign(secret: str, method: str, path: str, user_id: str, body: bytes = b"", *, now: float | None = None) -> str:
    ts = int(now if now is not None else time.time())
    digest = hmac.new(secret.encode(), _message(ts, method, path, user_id, body), hashlib.sha256).hexdigest()
    return f"{VERSION};{key_id(secret)};{ts};{digest}"


def verify(secrets: list[str], header: str | None, method: str, path: str, user_id: str, body: bytes = b"", *,
           now: float | None = None) -> bool:
    if not header or not secrets:
        return False
    try:
        version, kid, ts_text, digest = header.split(";")
        ts = int(ts_text)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if version != VERSION or abs(current - ts) > MAX_SKEW_SECONDS:
        return False
    for secret in secrets:
        if kid != key_id(secret):
            continue
        expected = hmac.new(secret.encode(), _message(ts, method, path, user_id, body), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, digest):
            return True
    return False
