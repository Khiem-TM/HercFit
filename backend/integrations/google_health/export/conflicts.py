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
from integrations.google_health.export.dispatch import _typed, _shape
from integrations.google_health.export import jobs

async def resolve(session, user_id: UUID, conflict_id: UUID, resolution: str) -> dict:
    from domains.shared.models.domain import lock_user
    await lock_user(session, user_id)
    row = (await session.execute(text("""
        SELECT x.id, x.local_payload, x.remote_payload, x.detected_at, x.outbox_id, m.id AS mapping_id, m.data_type,
               m.aggregate_type, m.aggregate_id, m.connection_id, o.aggregate_version, o.export_group, o.op
        FROM export_conflicts x JOIN google_resource_mappings m ON m.id = x.mapping_id
        LEFT JOIN export_outbox o ON o.id = x.outbox_id
        WHERE x.id = :id AND x.user_id = :u AND x.resolution IS NULL FOR UPDATE OF x"""),
        {"id": conflict_id, "u": user_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Conflict not found")
    remote = row["remote_payload"] or {}
    local = row["local_payload"]
    if resolution == "KEEP_LOCAL":
        # The user may have edited again while this conflict was waiting. Keep the
        # newest local intent, never replay the stale payload shown by the conflict.
        latest = (await session.execute(text("SELECT payload, op, aggregate_version FROM export_outbox "
            "WHERE mapping_id = :m AND state NOT IN ('SUPERSEDED', 'FAILED') "
            "ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE"), {"m": row["mapping_id"]})).first()
        local = latest.payload if latest else row["local_payload"]
        await session.execute(text("UPDATE export_outbox SET state = 'SUPERSEDED', updated_at = now() "
            "WHERE mapping_id = :m AND state IN ('PENDING', 'BLOCKED_PERMISSION', 'CONFLICT')"), {"m": row["mapping_id"]})
        await session.execute(text("UPDATE google_resource_mappings SET state = 'CONFIRMED', remote_sha256 = :sha, "
            "confirmed_payload = CAST(:payload AS jsonb) WHERE id = :m"),
            {"m": row["mapping_id"], "sha": _typed(row["data_type"], remote), "payload": json.dumps(remote)})
        outbox_id = uuid7()
        await session.execute(text("""
            INSERT INTO export_outbox (id, user_id, connection_id, export_group, aggregate_type, aggregate_id,
                                       aggregate_version, op, data_type, idempotency_key, payload, payload_sha256, mapping_id)
            VALUES (:id, :u, :c, :g, :t, :a, :v, :op, :d, :key, CAST(:payload AS jsonb), :sha, :m)"""), {
            "id": outbox_id, "m": row["mapping_id"], "op": (latest.op if latest else row["op"]) or "UPDATE", "u": user_id, "c": row["connection_id"], "g": row["export_group"] or
            mapping.AGGREGATE_GROUPS[row["aggregate_type"]], "t": row["aggregate_type"], "a": row["aggregate_id"],
            "v": ((latest.aggregate_version if latest else row["aggregate_version"]) or 1) + 1_000_000, "d": row["data_type"],
            "key": f"keep-local:{conflict_id}", "payload": json.dumps(local), "sha": mapping.payload_sha256(local)})
        from integrations.google_health.models import HealthConnection
        connection = await session.get(HealthConnection, row["connection_id"])
        await jobs.enqueue(session, connection, event_id=outbox_id)
    else:
        from integrations.google_health.export.remote import accept
        entity = await accept(session, user_id, row, remote)
        payload = dict(mapping.build(row["aggregate_type"], entity)).get(row["data_type"], remote)
        await session.execute(text("UPDATE google_resource_mappings SET state = 'CONFIRMED', remote_sha256 = :sha, "
            "confirmed_payload = CAST(:payload AS jsonb), payload_sha256 = :local_sha WHERE id = :m"),
            {"m": row["mapping_id"], "sha": _typed(row["data_type"], remote, _shape(row["data_type"], payload)),
             "payload": json.dumps(payload), "local_sha": mapping.payload_sha256(payload)})
    await session.execute(text("UPDATE export_outbox SET state = 'SUPERSEDED', updated_at = now() WHERE id = :o"),
                          {"o": row["outbox_id"]})
    await session.execute(text("UPDATE export_conflicts SET resolution = :r, resolved_at = now() WHERE id = :id"),
                          {"r": resolution, "id": conflict_id})
    await session.commit()
    return {"id": row["id"], "data_type": row["data_type"], "aggregate_type": row["aggregate_type"],
            "aggregate_id": row["aggregate_id"], "local_payload": row["local_payload"], "remote_payload": remote,
            "detected_at": row["detected_at"]}
