"""Consent for the assistant to use health data: one decision for every read path.

* `load(session, user_id)` returns the current decision and its version.
* `grant` / `revoke` write user_consents + consent_events in the caller's
  transaction. The database trigger republishes device data to the knowledge
  graph (upsert or tombstone) in the same transaction, and a `consent.changed`
  domain event lets other stores (context snapshots, the agent's memory) purge.
* `device_access(session, user_id)` answers "may the current principal read
  device-measured data?": the user always may; the assistant only with consent.

Data groups: `device` (wearable/provider measurements and anything derived from
them) and `sensitive` (ECG/IRN, glucose, symptoms, mood, reproductive logs),
which needs its own, separate consent.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core import principal as principals
from domains.identity.models.consent import ConsentEvent, UserConsent

PURPOSE = "assistant"
POLICY_VERSION = "2026-11-01"
CONSENT_REQUIRED = {"code": "consent_required",
                    "message": "Người dùng chưa cho phép trợ lý dùng dữ liệu sức khoẻ từ thiết bị. "
                               "Có thể bật trong Cài đặt → Kết nối."}


@dataclass(frozen=True)
class ConsentState:
    device: bool = False
    sensitive: bool = False
    version: int = 0

    def allows(self, data_group: str) -> bool:
        return bool(getattr(self, data_group, False))


async def load(session: AsyncSession, user_id: UUID) -> ConsentState:
    rows = (await session.execute(select(UserConsent).where(
        UserConsent.user_id == user_id, UserConsent.purpose == PURPOSE))).scalars().all()
    granted = {row.data_group: row.granted for row in rows}
    return ConsentState(device=granted.get("device", False), sensitive=granted.get("sensitive", False),
                        version=max((row.version for row in rows), default=0))


async def _set(session: AsyncSession, user_id: UUID, data_group: str, granted: bool, actor: str) -> ConsentState:
    # Serialize consent changes per user so versions stay strictly increasing.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                          {"key": f"consent:{user_id}"})
    state = await load(session, user_id)
    row = await session.get(UserConsent, (user_id, PURPOSE, data_group))
    if row is not None and row.granted == granted:
        return state
    version = state.version + 1
    if row is None:
        session.add(UserConsent(user_id=user_id, purpose=PURPOSE, data_group=data_group, granted=granted,
                                version=version, policy_version=POLICY_VERSION))
    else:
        row.granted, row.version, row.policy_version = granted, version, POLICY_VERSION
        row.changed_at = text("now()")
    session.add(ConsentEvent(user_id=user_id, purpose=PURPOSE, data_group=data_group, granted=granted,
                             version=version, policy_version=POLICY_VERSION, actor=actor))
    await session.flush()
    # Contexts built under the previous decision must never be served again.
    await session.execute(text("DELETE FROM context_snapshots WHERE user_id = :u"), {"u": user_id})
    from domains.shared.events import publish
    await publish(session, "consent.changed", user_id,
                  {"purpose": PURPOSE, "data_group": data_group, "granted": granted, "version": version})
    return await load(session, user_id)


async def grant(session: AsyncSession, user_id: UUID, data_group: str = "device", *, actor: str = "USER") -> ConsentState:
    return await _set(session, user_id, data_group, True, actor)


async def revoke(session: AsyncSession, user_id: UUID, data_group: str = "device", *, actor: str = "USER") -> ConsentState:
    return await _set(session, user_id, data_group, False, actor)


async def set_device(session: AsyncSession, user_id: UUID, allowed: bool, *, actor: str = "USER") -> ConsentState:
    return await (grant if allowed else revoke)(session, user_id, "device", actor=actor)


async def device_access(session: AsyncSession, user_id: UUID, data_group: str = "device") -> bool:
    """May the current principal read device-measured data of this user?"""
    if not principals.is_agent():
        return True
    return (await load(session, user_id)).allows(data_group)


async def require_device_access(session: AsyncSession, user_id: UUID, data_group: str = "device") -> None:
    if not await device_access(session, user_id, data_group):
        raise HTTPException(403, CONSENT_REQUIRED)
