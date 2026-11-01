"""Google Health webhook endpoint: verify, persist, answer 204. Nothing else runs in the request.

Contract (developers.google.com/health/webhooks, checked 2026-11-01):
* Handshake: Google POSTs {"type": "verification"} twice: with the configured
  Authorization value we answer 200, without it 401.
* Every notification carries `Authorization` equal to the subscriber's configured
  `endpointAuthorization.secret` (scheme included, e.g. "Bearer ...") and
  `GOOGLE-HEALTH-API-SIGNATURE`: base64 of a 5-byte Tink prefix (version byte +
  4-byte key id) followed by a DER ECDSA P-256 / SHA-256 signature over the raw
  body. The public Tink keyset lives at settings.GH_WEBHOOK_KEYSET_URL; keys
  rotate every 30 days, so an unknown key id triggers one keyset refresh.
* The body is one {"data": {...}} object or an array of up to 99 of them; Google
  retries for 7 days and may deliver duplicates.

Each message is stored in webhook_inbox (deduplicated by its hash) and committed
before 204 is returned; a storage failure answers 503 so Google retries.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from core.database import get_db_session
from core.settings import settings
from domains.shared.models.basemodel import uuid7

logger = logging.getLogger(__name__)
SIGNATURE_HEADER = "GOOGLE-HEALTH-API-SIGNATURE"
MAX_BODY_BYTES = 256 * 1024
MAX_MESSAGES = 99
KEYSET_TTL_SECONDS = 3600
TINK_PREFIX = 0x01


# ------------------------------------------------------------------------------------------- keys
def _varint(data: bytes, index: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, index
        shift += 7


def ecdsa_public_key(serialized: bytes) -> ec.EllipticCurvePublicKey:
    """Parse a Tink EcdsaPublicKey protobuf (x = field 3, y = field 4, big-endian) into a P-256 key."""
    fields: dict[int, bytes] = {}
    index = 0
    while index < len(serialized):
        key, index = _varint(serialized, index)
        number, wire = key >> 3, key & 7
        if wire == 0:
            _, index = _varint(serialized, index)
        elif wire == 2:
            length, index = _varint(serialized, index)
            fields[number] = serialized[index:index + length]
            index += length
        else:
            raise ValueError("unsupported protobuf wire type")
    x, y = int.from_bytes(fields[3], "big"), int.from_bytes(fields[4], "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


class Keyset:
    """Tink JSON keyset {"key": [{"keyId", "keyData": {"value"}, "outputPrefixType", "status"}]} with a TTL cache."""

    def __init__(self, url: str, fetch=None):
        self.url = url
        self._fetch = fetch
        self._keys: dict[int, tuple[ec.EllipticCurvePublicKey, str]] = {}
        self._loaded_at = 0.0

    def load(self, document: dict[str, Any]) -> None:
        keys = {}
        for entry in document.get("key") or []:
            if entry.get("status", "ENABLED") != "ENABLED":
                continue
            value = base64.b64decode((entry.get("keyData") or {}).get("value") or "")
            keys[int(entry["keyId"])] = (ecdsa_public_key(value), entry.get("outputPrefixType", "TINK"))
        self._keys, self._loaded_at = keys, time.monotonic()

    async def refresh(self) -> None:
        if self._fetch is not None:
            self.load(await self._fetch(self.url))
            return
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            self.load(response.json())

    async def key(self, key_id: int | None):
        stale = time.monotonic() - self._loaded_at > KEYSET_TTL_SECONDS
        if stale or (key_id is not None and key_id not in self._keys):
            await self.refresh()
        return self._keys.get(key_id) if key_id is not None else None

    def raw_keys(self):
        return [key for key, prefix in self._keys.values() if prefix == "RAW"]


_keyset: Keyset | None = None


def keyset() -> Keyset:
    global _keyset
    if _keyset is None or _keyset.url != settings.GH_WEBHOOK_KEYSET_URL:
        _keyset = Keyset(settings.GH_WEBHOOK_KEYSET_URL)
    return _keyset


# ------------------------------------------------------------------------------------------- checks
def authorized(header: str | None) -> bool:
    if not header:
        return False
    return any(hmac.compare_digest(header.encode(), secret.encode()) for secret in settings.webhook_secrets)


async def signature_valid(body: bytes, header: str | None, keys: Keyset | None = None) -> tuple[bool, str | None]:
    """(valid, key id) for GOOGLE-HEALTH-API-SIGNATURE over the raw body."""
    if not header:
        return False, None
    try:
        signature = base64.b64decode(header, validate=True)
    except ValueError:
        return False, None
    keys = keys or keyset()
    candidates = []
    if len(signature) > 5 and signature[0] == TINK_PREFIX:
        key_id = int.from_bytes(signature[1:5], "big")
        found = await keys.key(key_id)
        if found is not None:
            candidates.append((found[0], signature[5:], str(key_id)))
    if not candidates:
        await keys.key(None)
        candidates = [(key, signature, "raw") for key in keys.raw_keys()]
    for public_key, der, key_id in candidates:
        try:
            public_key.verify(der, body, ec.ECDSA(hashes.SHA256()))
            return True, key_id
        except InvalidSignature:
            continue
    return False, None


def messages(document: Any) -> list[dict[str, Any]]:
    items = document if isinstance(document, list) else [document]
    return [item["data"] for item in items[:MAX_MESSAGES] if isinstance(item, dict) and isinstance(item.get("data"), dict)]


async def store(subscriber: str, items: list[dict[str, Any]], key_id: str | None) -> int:
    """Persist messages (one row each, duplicates ignored) and commit; returns how many were new."""
    stored = 0
    async with get_db_session() as session:
        for item in items:
            canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            result = await session.execute(text("""
                INSERT INTO webhook_inbox (id, subscriber, health_user_id, data_type, operation, intervals,
                                           message_sha256, message, key_id)
                VALUES (:id, :subscriber, :user, :data_type, :operation, CAST(:intervals AS jsonb), :sha,
                        CAST(:message AS jsonb), :key_id)
                ON CONFLICT (message_sha256) DO NOTHING"""), {
                "id": uuid7(), "subscriber": subscriber[:64], "user": str(item.get("healthUserId") or "")[:255] or None,
                "data_type": str(item.get("dataType") or "")[:60] or None,
                "operation": str(item.get("operation") or "")[:10] or None,
                "intervals": json.dumps(item.get("intervals") or []),
                "sha": hashlib.sha256(canonical.encode()).hexdigest(), "message": canonical, "key_id": key_id})
            stored += result.rowcount or 0
        if stored and settings.GH_INGEST_V2 != "off":
            # Route right away (same transaction, deduplicated) rather than at the next scheduler tick.
            from core.jobs import queue
            await queue.enqueue(session, "GH_WEBHOOK_ROUTE", dedupe_key="webhook-route", priority=95)
    return stored


# ------------------------------------------------------------------------------------------- endpoint
router = APIRouter(prefix="/integrations/google-health", tags=["integrations"])


@router.post("/webhooks/{subscriber}", include_in_schema=False)
async def receive(subscriber: str, request: Request) -> Response:
    if not settings.GH_WEBHOOK_ENABLED or not settings.webhook_secrets:
        return Response(status_code=404)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response(status_code=413)
    try:
        document = json.loads(body or b"null")
    except ValueError:
        return Response(status_code=400)
    if not authorized(request.headers.get("authorization")):
        return Response(status_code=401)
    if isinstance(document, dict) and document.get("type") == "verification":
        return Response(status_code=200)
    key_id = None
    if settings.GH_WEBHOOK_VERIFY_SIGNATURE:
        try:
            valid, key_id = await signature_valid(body, request.headers.get(SIGNATURE_HEADER))
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("google_health_webhook_keyset_unavailable")
            return Response(status_code=503)
        if not valid:
            return Response(status_code=401)
    items = messages(document)
    try:
        stored = await store(subscriber, items, key_id)
    except Exception as exc:  # noqa: BLE001 - never acknowledge what was not stored
        logger.warning("google_health_webhook_store_failed error=%s", type(exc).__name__)
        return Response(status_code=503)
    logger.info("google_health_webhook messages=%s new=%s", len(items), stored)
    return Response(status_code=204)
