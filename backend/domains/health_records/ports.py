"""Ports the health-records domain needs from provider integrations.

Business code must not import a provider package. A provider integration
registers an implementation at import time (integrations/google_health/directory.py);
without one, every user simply has no provider link.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    status: str                       # ACTIVE, NEEDS_REAUTH, REVOKED, ERROR
    provider_profile: dict[str, Any] = field(default_factory=dict)
    last_success_at: datetime | None = None

    @property
    def connected(self) -> bool:
        return self.status in {"ACTIVE", "NEEDS_REAUTH"}


@dataclass(frozen=True)
class TypeAvailability:
    """Per data type: granted by the user, enabled by HercFit, and synced through which date."""
    granted: bool
    enabled: bool
    complete_through: Any = None


class ProviderDirectory(Protocol):
    async def status(self, session: AsyncSession, user_id: UUID) -> ProviderStatus | None: ...

    async def availability(self, session: AsyncSession, user_id: UUID) -> dict[str, TypeAvailability]: ...

    async def before_account_erasure(self, session: AsyncSession, user_id: UUID) -> None:
        """Revoke provider grants (best effort) before the account row is deleted."""


_directories: list[ProviderDirectory] = []


def register(directory: ProviderDirectory) -> None:
    if all(type(existing) is not type(directory) for existing in _directories):
        _directories.append(directory)


async def provider_status(session: AsyncSession, user_id: UUID) -> ProviderStatus | None:
    for directory in _directories:
        found = await directory.status(session, user_id)
        if found is not None:
            return found
    return None


async def before_account_erasure(session: AsyncSession, user_id: UUID) -> None:
    for directory in _directories:
        await directory.before_account_erasure(session, user_id)


async def availability(session: AsyncSession, user_id: UUID) -> dict[str, TypeAvailability]:
    merged: dict[str, TypeAvailability] = {}
    for directory in _directories:
        merged.update(await directory.availability(session, user_id))
    return merged
