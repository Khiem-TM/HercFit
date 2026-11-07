"""Chứng thực tra cứu: service tra cứu ký những gì nó đã kiểm chứng, API kiểm tra chữ ký.

Chữ ký bao gồm chủ sở hữu, miền và nội dung tra cứu bất biến (id ứng viên,
truy vấn, payload, bằng chứng và nguồn). Các trường giải quyết catalog (resolution, fingerprints,
bản ghi có sẵn, revision) không được ký: người dùng có thể đổi chúng sau xung đột mà không
chạy lại tra cứu, và API kiểm tra lại chúng với catalog hiện tại ở mỗi lần finalize.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

SIGNED_FIELDS = ("candidate_id", "query", "payload", "evidence", "sources")
VERSION = 1


def key_id(secret):
    return hashlib.sha256(("hercfit-research:" + secret).encode()).hexdigest()[:12]


def _owner(owner_id):
    try:
        return str(UUID(str(owner_id)))
    except ValueError:
        return str(owner_id)


def _message(owner_id, domain, content, issued_at):
    body = {
        "v": VERSION,
        "owner": _owner(owner_id),
        "domain": domain,
        "issued_at": issued_at,
        **{field: content[field] for field in SIGNED_FIELDS},
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(secret, owner_id, domain, content, issued_at=None):
    """content là bản dump chế độ JSON của một Finalization (các trường không ký bị bỏ qua)."""
    issued_at = issued_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    signature = hmac.new(
        secret.encode(), _message(owner_id, domain, content, issued_at), hashlib.sha256
    ).hexdigest()
    return {
        "version": VERSION,
        "key_id": key_id(secret),
        "issued_at": issued_at,
        "signature": signature,
    }


def verify(secrets, owner_id, domain, content, attestation, *, max_age, now=None):
    """Secret đã kiểm chứng chứng thực, hoặc None. Secret đã xoay vẫn hợp lệ để kiểm chứng."""
    if not attestation or attestation.get("version") != VERSION:
        return None
    try:
        issued = datetime.fromisoformat(attestation["issued_at"])
    except (KeyError, TypeError, ValueError):
        return None
    now = now or datetime.now(timezone.utc)
    if issued.tzinfo is None or issued > now + timedelta(minutes=5) or now - issued > max_age:
        return None
    message = _message(owner_id, domain, content, attestation["issued_at"])
    for secret in secrets:
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        if attestation.get("key_id") == key_id(secret) and hmac.compare_digest(
            expected, str(attestation.get("signature", ""))
        ):
            return secret
    return None
