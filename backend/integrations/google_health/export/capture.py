"""Capture business writes into export_outbox, in the business transaction.

A write is captured only when all hold:
* the record is HercFit's (not imported from Google) and the transaction is not
  an import (`SET LOCAL hercfit.origin = 'google'`), so nothing loops back;
* the user has an ACTIVE connection, enabled the export group, and granted its
  write scope; enabling a group exports changes made after that moment only
  (history export is a separate, explicit job);
* deletes are captured only when the user asked to delete the Google copy too.

Rows carry an idempotency key (aggregate, version, op, data type), the payload and
its hash. A replaced snapshot (meals, trainings, body metrics are immutable) moves
the Google mapping to the new aggregate and becomes an UPDATE of the same point.
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
    """Call in import transactions: writes in them are never exported back."""
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
    # A write captured live happens after the group was enabled, so it is a new change by
    # definition. Records made before enabling are only sent by the explicit history export.
    # (Comparing created_at with enabled_at would mix the app's and the database's clocks.)
    points = mapping.build(aggregate_type, entity)
    written = 0
    for data_type, payload in points:
        if not contract_scopes.can_write(spec(data_type).scope_group, connection.granted_scopes or []):
            continue
        if replaces_id is not None:
            # The immutable snapshot was replaced: the same Google point now follows the new aggregate.
            await session.execute(text("""
                UPDATE google_resource_mappings SET aggregate_id = :new, updated_at = now()
                WHERE connection_id = :c AND aggregate_type = :t AND aggregate_id = :old AND data_type = :d"""),
                {"new": entity.id, "old": replaces_id, "c": connection.id, "t": aggregate_type, "d": data_type})
        exists = (await session.execute(text("""
            SELECT id, state, payload_sha256 FROM google_resource_mappings WHERE connection_id = :c AND aggregate_type = :t
              AND aggregate_id = :a AND data_type = :d"""),
            {"c": connection.id, "t": aggregate_type, "a": entity.id, "d": data_type})).first()
        if history and exists and exists.state == "CONFIRMED" and exists.payload_sha256 == mapping.payload_sha256(payload):
            continue  # already on Google, unchanged: a history export sends it only once
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
    """The Google effects a write would have (shown on the confirmation card, bound at execution)."""
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
