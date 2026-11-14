"""A sync may commit only while its connection generation is still current.

The row lock is held only inside each short DB transaction, never over HTTP.
Disconnect, purge and reconnect change the generation under the same row lock.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from core.database import get_db_session
from integrations.google_health.models import HealthConnection


class SyncSuperseded(Exception):
    pass


@dataclass(frozen=True)
class SyncFence:
    connection_id: UUID
    generation: int


current: ContextVar[SyncFence | None] = ContextVar("health_sync_fence", default=None)


async def check(session):
    fence = current.get()
    if fence is None:  # Isolated provider adapters/tests; production enters through sync.run.
        return
    row = await session.scalar(select(HealthConnection).where(
        HealthConnection.id == fence.connection_id).with_for_update().execution_options(populate_existing=True))
    if row is None or row.status != "ACTIVE" or row.sync_generation != fence.generation:
        raise SyncSuperseded()


async def before_request():
    async with get_db_session() as session:
        await check(session)
