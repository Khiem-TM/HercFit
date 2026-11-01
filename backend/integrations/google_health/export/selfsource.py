"""Recognize data HercFit itself wrote to Google, so an import never duplicates it.

A point is ours when its resource name is in google_resource_mappings (owned by
HercFit) or its data source names our OAuth client (`application.googleWebClientId`).
Rollups cannot be filtered this way: they aggregate all sources, so daily totals may
include exported logs; context and insights therefore report logs and provider
totals per source instead of adding them.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from core.settings import settings


async def owned_names(session, connection_id: UUID, data_type: str) -> set[str]:
    rows = await session.execute(text("""
        SELECT remote_name FROM google_resource_mappings
        WHERE connection_id = :c AND data_type = :d AND owned_by_hercfit AND remote_name IS NOT NULL"""),
        {"c": connection_id, "d": data_type})
    return {row[0] for row in rows}


def written_by_us(data_source: dict[str, Any] | None) -> bool:
    application = (data_source or {}).get("application") or {}
    client = settings.GOOGLE_OAUTH_CLIENT_ID
    return bool(client and application.get("googleWebClientId") == client)
