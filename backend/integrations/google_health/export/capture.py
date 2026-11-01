"""Ghi nhận lệnh ghi nghiệp vụ vào export_outbox, trong transaction nghiệp vụ.

Một lệnh ghi chỉ được ghi nhận khi thoả mọi điều kiện:
* bản ghi thuộc HercFit (không nhập từ Google) và transaction không phải
  lần nhập (`SET LOCAL hercfit.origin = 'google'`), nên không gì vòng ngược lại;
* người dùng có kết nối ACTIVE, đã bật nhóm xuất và đã cấp scope ghi
  của nó; bật một nhóm chỉ xuất các thay đổi sau thời điểm đó
  (xuất lịch sử là job riêng, tường minh);
* lệnh xoá chỉ được ghi nhận khi người dùng yêu cầu xoá cả bản trên Google.

Các dòng mang khoá idempotency (aggregate, phiên bản, thao tác, loại dữ liệu), payload và
băm của nó. Ảnh chụp bị thay (bữa ăn, buổi tập, số đo cơ thể là bất biến) chuyển
mapping Google sang aggregate mới và trở thành UPDATE của cùng data point.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from domains.shared.models.basemodel import uuid7
from integrations.google_health.contract import scopes as contract_scopes
from integrations.google_health.contract.registry import spec
from integrations.google_health.export import mapping


async def _origin(session) -> str | None:
    return (await session.execute(text("SELECT current_setting('hercfit.origin', true)"))).scalar()


async def mark_import(session) -> None:
    """Gọi trong transaction nhập: lệnh ghi trong đó không bao giờ được xuất ngược lại."""
    await session.execute(text("SELECT set_config('hercfit.origin', 'google', true)"))


async def _connection(session, user_id: UUID):
    return (await session.execute(text("""
        SELECT c.id, c.granted_scopes FROM health_connections c
        WHERE c.user_id = :u AND c.status = 'ACTIVE' AND c.is_active"""), {"u": user_id})).first()


async def _setting(session, connection_id: UUID, group: str):
    return (await session.execute(text("""
        SELECT enabled, enabled_at FROM google_export_settings WHERE connection_id = :c AND export_group = :g"""),
        {"c": connection_id, "g": group})).first()


async def capture(session, user_id: UUID, aggregate_type: str, entity: Any, op: str, *, replaces_id: UUID | None = None,
                  remote: bool = False, history: bool = False, operation_id: UUID | None = None) -> int:
    group = mapping.AGGREGATE_GROUPS.get(aggregate_type)
    if group is None or getattr(entity, "source", "MANUAL") == "GOOGLE_HEALTH" or await _origin(session) == "google":
        return 0
    if op == "DELETE" and not remote:
        return 0
    connection = await _connection(session, user_id)
    if connection is None:
        return 0
    setting = await _setting(session, connection.id, group)
    if setting is None or not setting.enabled:
        return 0
    # Một lệnh ghi được ghi nhận trực tiếp xảy ra sau khi nhóm được bật, nên theo định nghĩa
    # nó là thay đổi mới. Bản ghi tạo trước khi bật chỉ được gửi bởi lệnh xuất lịch sử tường minh.
    # (So created_at với enabled_at sẽ trộn đồng hồ của ứng dụng và của database.)
    points = mapping.build(aggregate_type, entity)
    written = 0
    for data_type, payload in points:
        if not contract_scopes.can_write(spec(data_type).scope_group, connection.granted_scopes or []):
            continue
        if replaces_id is not None:
            # Ảnh chụp bất biến đã bị thay: cùng data point trên Google giờ đi theo aggregate mới.
            await session.execute(text("""
                UPDATE google_resource_mappings SET aggregate_id = :new, updated_at = now()
                WHERE connection_id = :c AND aggregate_type = :t AND aggregate_id = :old AND data_type = :d"""),
                {"new": entity.id, "old": replaces_id, "c": connection.id, "t": aggregate_type, "d": data_type})
        exists = (await session.execute(text("""
            SELECT id, state, payload_sha256 FROM google_resource_mappings WHERE connection_id = :c AND aggregate_type = :t
              AND aggregate_id = :a AND data_type = :d"""),
            {"c": connection.id, "t": aggregate_type, "a": entity.id, "d": data_type})).first()
        if history and exists and exists.state == "CONFIRMED" and exists.payload_sha256 == mapping.payload_sha256(payload):
            continue  # đã có trên Google và không đổi: xuất lịch sử chỉ gửi một lần
        effective = op if op == "DELETE" else ("UPDATE" if exists else "CREATE")
        if effective == "DELETE" and not exists:
            continue
        if exists is None:
            await session.execute(text("""
                INSERT INTO google_resource_mappings (id, connection_id, user_id, aggregate_type, aggregate_id, data_type,
                                                      client_id, local_version, state)
                VALUES (:id, :c, :u, :t, :a, :d, :client, :version, 'PENDING')"""),
                {"id": uuid7(), "c": connection.id, "u": user_id, "t": aggregate_type, "a": entity.id, "d": data_type,
                 "client": mapping.client_id(aggregate_type, entity.id, data_type),
                 "version": getattr(entity, "version_id", 1)})
        version = getattr(entity, "version_id", 1)
        result = await session.execute(text("""
            INSERT INTO export_outbox (id, user_id, connection_id, export_group, aggregate_type, aggregate_id,
                                       aggregate_version, op, data_type, idempotency_key, payload, payload_sha256,
                                       operation_id)
            VALUES (:id, :u, :c, :g, :t, :a, :v, :op, :d, :key, CAST(:payload AS jsonb), :sha, :operation)
            ON CONFLICT DO NOTHING"""), {
            "id": uuid7(), "u": user_id, "c": connection.id, "g": group, "t": aggregate_type, "a": entity.id,
            "v": version, "op": effective, "d": data_type,
            "key": f"{aggregate_type}:{entity.id}:{data_type}:{version}:{effective}",
            "payload": json.dumps(payload), "sha": mapping.payload_sha256(payload), "operation": operation_id})
        written += result.rowcount or 0
    return written


async def hook(session, user_id, aggregate_type, entity, op, **extra) -> None:
    await capture(session, user_id, aggregate_type, entity, op, replaces_id=extra.get("replaces_id"),
                  remote=extra.get("remote", False))


async def preview(session, user_id: UUID, aggregate_type: str, entity: Any) -> list[dict[str, Any]]:
    """Tác động lên Google mà một lệnh ghi sẽ có (hiển thị trên thẻ xác nhận, gắn lại lúc thực thi)."""
    group = mapping.AGGREGATE_GROUPS.get(aggregate_type)
    if group is None:
        return []
    connection = await _connection(session, user_id)
    setting = await _setting(session, connection.id, group) if connection else None
    if connection is None or setting is None or not setting.enabled:
        return []
    effects = []
    for data_type, payload in mapping.build(aggregate_type, entity):
        if contract_scopes.can_write(spec(data_type).scope_group, connection.granted_scopes or []):
            effects.append({"target": "google_health", "data_type": data_type, "op": "CREATE", "payload": payload,
                            "payload_sha256": mapping.payload_sha256(payload)})
    return effects
