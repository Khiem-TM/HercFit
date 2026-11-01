"""Access tokens for a connection: refreshed once, under a per-connection advisory lock.

Whoever waits on the lock re-reads the row and reuses the token the first caller
stored. `check(session)` runs inside the same transaction before anything is
written, so a run or job that lost its lease or generation never stores tokens.
invalid_grant raises ReauthRequired; a missing write scope never touches reads.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import text

from core.crypto import decrypt_secret, encrypt_secret
from core.database import get_db_session
from integrations.google_health import oauth
from integrations.google_health.client import ReauthRequired
from integrations.google_health.models import HealthConnection

SKEW = timedelta(seconds=60)


def _fresh(connection: HealthConnection) -> bool:
    return bool(connection.access_token_enc and connection.token_expires_at
                and connection.token_expires_at - SKEW > datetime.now(timezone.utc))


async def access_token(connection_id: UUID, http: httpx.AsyncClient, *,
                       check: Callable[[object], Awaitable[None]] | None = None) -> tuple[str, list[str]]:
    """(access token, granted scopes) for the connection."""
    async with get_db_session() as session:
        connection = await session.get(HealthConnection, connection_id)
        if connection is not None and _fresh(connection):
            return decrypt_secret(connection.access_token_enc), list(connection.granted_scopes or [])
    async with get_db_session() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                              {"key": f"gh-refresh:{connection_id}"})
        if check is not None:
            await check(session)
        connection = await session.get(HealthConnection, connection_id, populate_existing=True)
        if connection is None or connection.status != "ACTIVE":
            raise ReauthRequired()
        if _fresh(connection):
            return decrypt_secret(connection.access_token_enc), list(connection.granted_scopes or [])
        if not connection.refresh_token_enc:
            raise ReauthRequired()
        data = await oauth.refresh_access_token(http, decrypt_secret(connection.refresh_token_enc))
        connection.access_token_enc = encrypt_secret(data["access_token"])
        connection.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))
        if data.get("refresh_token"):
            connection.refresh_token_enc = encrypt_secret(data["refresh_token"])
        if data.get("scope"):
            connection.granted_scopes = oauth.granted_scopes(data)
        return data["access_token"], list(connection.granted_scopes or [])


async def mark_reauth(connection_id: UUID, generation: int | None = None) -> None:
    async with get_db_session() as session:
        await session.execute(text("""
            UPDATE health_connections SET status = 'NEEDS_REAUTH', next_sync_at = NULL,
                   last_error_code = 'reauth_required', updated_at = now()
            WHERE id = :id AND status = 'ACTIVE' AND (CAST(:generation AS bigint) IS NULL OR generation = :generation)"""),
            {"id": connection_id, "generation": generation})
