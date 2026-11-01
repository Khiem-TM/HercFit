"""Giải quyết một lần lệch cục bộ/từ xa mà người dùng đã được xem.

KEEP_LOCAL     trạng thái từ xa trở thành mốc mới và phiên bản của HercFit được gửi
               lại (một dòng outbox mới), chủ động ghi đè lần sửa từ xa.
ACCEPT_REMOTE  chấp nhận phiên bản từ xa: mapping lấy trạng thái từ xa làm
               đã xác nhận, và các trường nhật ký sửa được chép vào bản ghi cục bộ.
"""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from domains.shared.models.basemodel import uuid7
from integrations.google_health.export import mapping
from integrations.google_health.export.dispatch import _typed

REMOTE_FIELDS = {  # loại aggregate -> (bảng, trường loại dữ liệu, {cột cục bộ: đường dẫn từ xa})
    "HydrationLog": ("hydration_logs", "hydrationLog", {"amount_ml": ("amountConsumed", "milliliters")}),
    "OvulationTestLog": ("ovulation_test_logs", "ovulationTest", {"result": ("result",)}),
}


async def resolve(session, user_id: UUID, conflict_id: UUID, resolution: str) -> dict:
    row = (await session.execute(text("""
        SELECT x.id, x.local_payload, x.remote_payload, x.detected_at, x.outbox_id, m.id AS mapping_id, m.data_type,
               m.aggregate_type, m.aggregate_id, m.connection_id, o.aggregate_version, o.export_group
        FROM export_conflicts x JOIN google_resource_mappings m ON m.id = x.mapping_id
        LEFT JOIN export_outbox o ON o.id = x.outbox_id
        WHERE x.id = :id AND x.user_id = :u AND x.resolution IS NULL FOR UPDATE OF x"""),
        {"id": conflict_id, "u": user_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Conflict not found")
    remote = row["remote_payload"] or {}
    remote_sha = _typed(row["data_type"], remote, None) if remote else None
    if resolution == "KEEP_LOCAL":
        local = row["local_payload"]
        keys = set((local.get(next(iter(k for k in local if k != "dataSource"), "")) or {}).keys())
        await session.execute(text("UPDATE google_resource_mappings SET state = 'CONFIRMED', remote_sha256 = :sha "
                                   "WHERE id = :m"), {"m": row["mapping_id"],
                                                      "sha": _typed(row["data_type"], remote, keys) if remote else None})
        await session.execute(text("""
            INSERT INTO export_outbox (id, user_id, connection_id, export_group, aggregate_type, aggregate_id,
                                       aggregate_version, op, data_type, idempotency_key, payload, payload_sha256)
            VALUES (:id, :u, :c, :g, :t, :a, :v, 'UPDATE', :d, :key, CAST(:payload AS jsonb), :sha)"""), {
            "id": uuid7(), "u": user_id, "c": row["connection_id"], "g": row["export_group"] or
            mapping.AGGREGATE_GROUPS[row["aggregate_type"]], "t": row["aggregate_type"], "a": row["aggregate_id"],
            "v": (row["aggregate_version"] or 1) + 1_000_000, "d": row["data_type"],
            "key": f"keep-local:{conflict_id}", "payload": json.dumps(local), "sha": mapping.payload_sha256(local)})
    else:
        await session.execute(text("UPDATE google_resource_mappings SET state = 'CONFIRMED', remote_sha256 = :sha "
                                   "WHERE id = :m"), {"m": row["mapping_id"], "sha": remote_sha})
        target = REMOTE_FIELDS.get(row["aggregate_type"])
        if target and remote:
            table, field, columns = target
            value = remote.get(field) or {}
            for column, path in columns.items():
                current = value
                for part in path:
                    current = (current or {}).get(part)
                if current is not None:
                    await session.execute(text(f"UPDATE {table} SET {column} = :value, version_id = version_id + 1, "
                                               f"updated_at = now() WHERE id = :id AND user_id = :u"),
                                          {"value": current, "id": row["aggregate_id"], "u": user_id})
    await session.execute(text("UPDATE export_conflicts SET resolution = :r, resolved_at = now() WHERE id = :id"),
                          {"r": resolution, "id": conflict_id})
    await session.commit()
    return {"id": row["id"], "data_type": row["data_type"], "aggregate_type": row["aggregate_type"],
            "aggregate_id": row["aggregate_id"], "local_payload": row["local_payload"], "remote_payload": remote,
            "detected_at": row["detected_at"]}
