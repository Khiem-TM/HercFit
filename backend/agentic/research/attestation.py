"""Research attestation: the research service signs what it verified, the API checks the signature.

The signature covers the owner, domain and the immutable research content (candidate id,
query, payload, evidence and sources). Catalog resolution fields (resolution, fingerprints,
existing record, revision) are excluded: the user may change them after a conflict without
re-running research, and the API re-checks them against the live catalog on every finalize.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

SIGNED_FIELDS = ('candidate_id', 'query', 'payload', 'evidence', 'sources')
VERSION = 1


def key_id(secret):
    return hashlib.sha256(('hercfit-research:' + secret).encode()).hexdigest()[:12]


def _owner(owner_id):
    try:
        return str(UUID(str(owner_id)))
    except ValueError:
        return str(owner_id)


def _message(owner_id, domain, content, issued_at):
    body = {'v': VERSION, 'owner': _owner(owner_id), 'domain': domain, 'issued_at': issued_at,
            **{field: content[field] for field in SIGNED_FIELDS}}
    return json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sign(secret, owner_id, domain, content, issued_at=None):
    """content is the JSON-mode dump of a Finalization (unsigned fields are ignored)."""
    issued_at = issued_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    signature = hmac.new(secret.encode(), _message(owner_id, domain, content, issued_at), hashlib.sha256).hexdigest()
    return {'version': VERSION, 'key_id': key_id(secret), 'issued_at': issued_at, 'signature': signature}


def verify(secrets, owner_id, domain, content, attestation, *, max_age, now=None):
    """The secret that verified the attestation, or None. Rotated secrets stay valid for verification."""
    if not attestation or attestation.get('version') != VERSION:
        return None
    try:
        issued = datetime.fromisoformat(attestation['issued_at'])
    except (KeyError, TypeError, ValueError):
        return None
    now = now or datetime.now(timezone.utc)
    if issued.tzinfo is None or issued > now + timedelta(minutes=5) or now - issued > max_age:
        return None
    message = _message(owner_id, domain, content, attestation['issued_at'])
    for secret in secrets:
        expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        if attestation.get('key_id') == key_id(secret) and hmac.compare_digest(expected, str(attestation.get('signature', ''))):
            return secret
    return None
