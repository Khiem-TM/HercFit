"""Một công tắc để đồng bộ HercFit lên Google Health (người dùng bật một lần).

Bật: mọi nhóm xuất đã mở (GH_EXPORT_GROUPS) và đã kiểm chứng đều được bật,
và các bản ghi HercFit đang có được gửi một lần (một operation lịch sử); các thay đổi
sau đó đi qua capture. Khi còn thiếu quyền Google, bên gọi xin
tất cả trên một màn hình đồng ý và OAuth callback bật nốt
công tắc (`then="export_all"` trong state đã ký).
Tắt: không nhóm nào gửi gì nữa; việc đọc từ Google không bị ảnh hưởng, và dữ liệu
đã có trên Google vẫn ở đó.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from core.jobs import queue
from core.settings import settings
from domains.shared import operations
from integrations.google_health.contract import scopes as contract_scopes
from integrations.google_health.contract.registry import EXPORT_GROUPS, EXPORT_ROLLOUT, Op, runtime_enabled, spec

INTENT = "export_all"
GROUP_LABELS = {"body": "Chỉ số cơ thể", "hydration": "Nước uống", "nutrition": "Dinh dưỡng", "workout": "Buổi tập",
                "sleep": "Giấc ngủ", "symptoms": "Triệu chứng", "mood": "Tâm trạng", "reproductive": "Sức khoẻ sinh sản"}


def available_groups() -> list[str]:
    """Các nhóm mà bản triển khai này được ghi: đã mở và lệnh tạo của mọi loại đều đã kiểm chứng."""
    verified = settings.verified_capabilities
    return [group for group in EXPORT_ROLLOUT if group in settings.GH_EXPORT_GROUPS
            and all(runtime_enabled(data_type, Op.CREATE, verified=verified) for data_type in EXPORT_GROUPS[group])]


def _writable(group: str, granted: list[str]) -> bool:
    return all(contract_scopes.can_write(spec(data_type).scope_group, granted) for data_type in EXPORT_GROUPS[group])


def missing_bundles(granted: list[str]) -> list[str]:
    """Mọi thứ công tắc cần mà người dùng chưa cấp: các gói đọc và các
    gói ghi của nhóm khả dụng, xin cùng lúc trên một màn hình đồng ý."""
    owned = set(contract_scopes.granted_bundles(granted))
    reads = [key for key in contract_scopes.CORE_READ if key not in owned]
    writes = [contract_scopes.EXPORT_GROUP_BUNDLES[group] for group in available_groups() if not _writable(group, granted)]
    return list(dict.fromkeys([*reads, *writes]))


async def state(session, connection) -> dict[str, Any]:
    granted = list(connection.granted_scopes or [])
    groups = available_groups()
    enabled = {row.export_group for row in (await session.execute(text(
        "SELECT export_group FROM google_export_settings WHERE connection_id = :c AND enabled"),
        {"c": connection.id})).all()}
    counts = {row.state: row.n for row in (await session.execute(text(
        "SELECT state, count(*) AS n FROM export_outbox WHERE connection_id = :c GROUP BY state"),
        {"c": connection.id})).all()}
    last = (await session.execute(text(
        "SELECT max(confirmed_at) FROM export_outbox WHERE connection_id = :c AND state = 'CONFIRMED'"),
        {"c": connection.id})).scalar()
    stranded = (await session.execute(text("SELECT count(*) FROM google_resource_mappings m "
        "WHERE m.connection_id = :c AND m.state = 'PENDING' AND m.remote_name IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM export_outbox o WHERE o.mapping_id = m.id)"),
        {"c": connection.id})).scalar() or 0
    on = bool(groups) and all(group in enabled for group in groups if _writable(group, granted)) \
        and any(group in enabled for group in groups)
    return {
        "available": bool(groups), "enabled": on, "partial": not on and bool(enabled & set(groups)),
        "groups": [{"group": group, "label": GROUP_LABELS[group], "enabled": group in enabled,
                    "write_scope_granted": _writable(group, granted)} for group in groups],
        "missing_bundles": missing_bundles(granted),
        "sent": counts.get("CONFIRMED", 0), "pending": counts.get("PENDING", 0) + counts.get("DISPATCHING", 0)
        + counts.get("VERIFYING", 0) + counts.get("SUBMITTED", 0),
        "attention": stranded + sum(counts.get(name, 0) for name in ("FAILED", "UNCERTAIN", "BLOCKED_PERMISSION", "CONFLICT")),
        "last_sent_at": last,
    }


async def enable_all(session, connection, user_id: UUID) -> UUID | None:
    """Bật mọi nhóm khả dụng mà các scope đã cấp cho phép và gửi những gì HercFit đang có.

    Trả về operation lịch sử (None khi không bật được nhóm nào). Chạy trong transaction
    của bên gọi: request API, hoặc OAuth callback sau khi người dùng đã cấp scope.
    """
    granted = list(connection.granted_scopes or [])
    groups = [group for group in available_groups() if _writable(group, granted)]
    if not groups:
        return None
    for group in groups:
        await session.execute(text("""
            INSERT INTO google_export_settings (connection_id, export_group, enabled, enabled_at, updated_at)
            VALUES (:c, :g, true, now(), now())
            ON CONFLICT (connection_id, export_group) DO UPDATE SET enabled = true,
                enabled_at = CASE WHEN google_export_settings.enabled THEN google_export_settings.enabled_at ELSE now() END,
                updated_at = now()"""), {"c": connection.id, "g": group})
    operation_id = await operations.create(session, user_id, "health.history_export", {"groups": groups})
    from integrations.google_health.export import jobs
    await jobs.enqueue(session, connection, event_id=operation_id, operation_id=operation_id)
    for group in groups:
        await queue.enqueue(session, "GH_HISTORY_EXPORT", queue="export", user_id=user_id, connection_id=connection.id,
                            connection_generation=connection.generation, operation_id=operation_id,
                            dedupe_key=f"history:{connection.id}:{group}", payload={"group": group}, priority=20)
    await session.execute(text("""
        UPDATE google_export_settings SET history_operation_id = :o
        WHERE connection_id = :c AND export_group = ANY(:groups)"""),
        {"o": operation_id, "c": connection.id, "groups": groups})
    return operation_id


async def disable_all(session, connection) -> None:
    await session.execute(text("""
        UPDATE google_export_settings SET enabled = false, updated_at = now() WHERE connection_id = :c AND enabled"""),
        {"c": connection.id})
