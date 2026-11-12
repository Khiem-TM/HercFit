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
from domains.health_records.types import TYPES, Read, disabled_types
from integrations.google_health.models import HealthConnection

logger = logging.getLogger(__name__)
PUSHED = {"Training", "Meal"}
# Loại chỉ ghi được qua Google trước đây; nay tạo mới luôn lưu trong HercFit dù chưa kết nối.
LOCAL_FIRST = {"exercise", "hydration", "sleep"}


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
                                    last_success_at=connection.last_success_at, timezone=connection.timezone)

    async def availability(self, session, user_id: UUID) -> dict[str, ports.TypeAvailability]:
        connection = await HealthConnection.for_user(session, user_id)
        if connection is None:
            return {}
        granted = set(connection.granted_scopes or [])
        cursor = connection.sync_cursor or {}
        off = disabled_types(connection.sync_groups)
        return {item.id: ports.TypeAvailability(
                    granted=item.read_scope in granted, enabled=item.id not in off,
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
        connected = (connection is not None and connection.status == "ACTIVE"
                     and can_write(records.DATA_TYPE[kind], connection.granted_scopes or []))
        if point_id is None and not delete:
            if connected or kind in LOCAL_FIRST:
                return await records.create(session, user_id, kind, payload or {})
            return None  # số đo khi chưa kết nối hoặc chưa cấp quyền ghi: miền lưu vào body_metrics như trước
        # Sửa / xoá một bản ghi HercFit đã lưu trong health_points: records chọn đường cục bộ hay Google.
        if delete:
            await records.delete(session, user_id, kind, point_id)
            return {"deleted": True}
        return await records.update(session, user_id, kind, point_id, payload or {})

    async def refresh(self, user_id: UUID, days: int = 2) -> bool:
        """Đồng bộ ngay vài ngày gần nhất (trước briefing buổi sáng); False khi chưa kết nối hoặc người dùng
        chọn chỉ đồng bộ khi mở ứng dụng / thủ công (đồng bộ nền là việc của tần suất "hourly")."""
        from core.database import get_db_session
        from integrations.google_health import sync

        async with get_db_session() as session:
            connection = await HealthConnection.for_user(session, user_id)
        if connection is None or (connection.sync_frequency or "hourly") != "hourly":
            return False
        result = await sync.run(user_id, days=days)
        return result.get("status") in {"ok", "partial"}

    async def before_account_erasure(self, session, user_id: UUID) -> None:
        from integrations.google_health.connection import revoke_connection

        connection = await HealthConnection.for_user(session, user_id)
        if connection is not None:
            await revoke_connection(connection)


async def push_after_commit(session, user_id: UUID, aggregate_type: str, entity: Any, op: str, **_extra: Any) -> None:
    """Buổi gym / bữa ăn vừa đổi: sau khi commit, đẩy ngay lên Google (lượt định kỳ vẫn bắt lại nếu lỡ)."""
    if aggregate_type in PUSHED:
        schedule_push(session, user_id)


def schedule_push(session, user_id: UUID) -> None:
    """Sau khi transaction commit, chạy một lượt chỉ đẩy cho user (mỗi transaction tối đa một lượt)."""
    if session.info.get("gh_push_scheduled"):
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
