"""Bản cài đặt của Google Health cho các port của miền health-records, và hook ghi."""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import event, text

from domains.health_records import ports
from domains.health_records.schemas.health import HEALTH_PROVIDER
from domains.health_records.types import TYPES, Read
from integrations.google_health.models import HealthConnection

logger = logging.getLogger(__name__)
PUSHED = {"Training", "Meal"}


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class GoogleHealthDirectory:
    async def status(self, session, user_id: UUID) -> ports.ProviderStatus | None:
        connection = await HealthConnection.for_user(session, user_id)
        if connection is None:
            return None
        return ports.ProviderStatus(provider=HEALTH_PROVIDER, status=connection.status,
                                    provider_profile=dict(connection.provider_profile or {}),
                                    last_success_at=connection.last_success_at)

    async def availability(self, session, user_id: UUID) -> dict[str, ports.TypeAvailability]:
        connection = await HealthConnection.for_user(session, user_id)
        if connection is None:
            return {}
        granted = set(connection.granted_scopes or [])
        cursor = connection.sync_cursor or {}
        return {item.id: ports.TypeAvailability(
                    granted=item.read_scope in granted, enabled=True,
                    complete_through=_day((cursor.get(item.id) or {}).get("through")),
                    complete_from=_day((cursor.get(item.id) or {}).get("from")))
                for item in TYPES.values() if item.read is not Read.NONE}

    async def linked_trainings(self, session, user_id: UUID) -> set[UUID]:
        rows = await session.execute(text("SELECT record_id FROM google_pushes WHERE user_id = :u "
                                          "AND record_type = 'Training' AND NOT owned"), {"u": user_id})
        return {record_id for (record_id,) in rows}

    async def write(self, session, user_id: UUID, kind: str, payload: dict[str, Any] | None = None,
                    point_id: UUID | None = None, delete: bool = False) -> dict[str, Any] | None:
        from domains.health_records.types import can_write
        from integrations.google_health import records

        connection = await HealthConnection.for_user(session, user_id)
        # Chưa kết nối hoặc chưa cấp quyền ghi loại này: miền lưu trong HercFit như trước.
        if (connection is None or connection.status != "ACTIVE"
                or not can_write(records.DATA_TYPE[kind], connection.granted_scopes or [])):
            return None
        if delete:
            await records.delete(session, user_id, kind, point_id)
            return {"deleted": True}
        if point_id is not None:
            return await records.update(session, user_id, kind, point_id, payload or {})
        return await records.create(session, user_id, kind, payload or {})

    async def before_account_erasure(self, session, user_id: UUID) -> None:
        from integrations.google_health.connection import revoke_connection

        connection = await HealthConnection.for_user(session, user_id)
        if connection is not None:
            await revoke_connection(connection)


async def push_after_commit(session, user_id: UUID, aggregate_type: str, entity: Any, op: str, **_extra: Any) -> None:
    """Buổi gym / bữa ăn vừa đổi: sau khi commit, đẩy ngay lên Google (lượt định kỳ vẫn bắt lại nếu lỡ)."""
    if aggregate_type not in PUSHED or session.info.get("gh_push_scheduled"):
        return
    session.info["gh_push_scheduled"] = True

    def schedule(_session) -> None:
        from integrations.google_health.sync import run

        _session.info.pop("gh_push_scheduled", None)
        try:
            asyncio.get_running_loop().create_task(run(user_id, push_only=True))
        except RuntimeError:  # không có vòng lặp sự kiện (script, test đồng bộ): để lượt định kỳ đẩy
            logger.debug("google_health_push_deferred user=%s", user_id)

    def forget(_session) -> None:
        _session.info.pop("gh_push_scheduled", None)

    event.listen(session.sync_session, "after_commit", schedule, once=True)
    event.listen(session.sync_session, "after_rollback", forget, once=True)


def _register() -> None:
    from domains.shared import write_hooks

    ports.register(GoogleHealthDirectory())
    write_hooks.register(push_after_commit)


_register()
