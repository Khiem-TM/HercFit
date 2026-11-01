"""One switch for syncing HercFit to Google Health (the user turns it on once).

On: every export group that is rolled out (GH_EXPORT_GROUPS) and verified is enabled,
and the records HercFit already holds are sent once (one history operation); later
changes follow through capture. When Google permissions are missing, the caller asks
for all of them on a single consent screen and the OAuth callback finishes turning the
switch on (`then="export_all"` in the signed state).
Off: no group sends anything any more; reading from Google is not affected, and data
already on Google stays there.
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
    """Groups this deployment may write: rolled out and every type's create verified."""
    verified = settings.verified_capabilities
    return [group for group in EXPORT_ROLLOUT if group in settings.GH_EXPORT_GROUPS
            and all(runtime_enabled(data_type, Op.CREATE, verified=verified) for data_type in EXPORT_GROUPS[group])]


def _writable(group: str, granted: list[str]) -> bool:
    return all(contract_scopes.can_write(spec(data_type).scope_group, granted) for data_type in EXPORT_GROUPS[group])


def missing_bundles(granted: list[str]) -> list[str]:
    """Everything the switch needs that the user has not granted: the read bundles and the
    write bundles of the available groups, asked for together on one consent screen."""
    owned = set(contract_scopes.granted_bundles(granted))
    reads = [key for key in contract_scopes.BUNDLES if not key.endswith("_write") and key not in owned]
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
    on = bool(groups) and all(group in enabled for group in groups if _writable(group, granted)) \
        and any(group in enabled for group in groups)
    return {
        "available": bool(groups), "enabled": on, "partial": not on and bool(enabled & set(groups)),
        "groups": [{"group": group, "label": GROUP_LABELS[group], "enabled": group in enabled,
                    "write_scope_granted": _writable(group, granted)} for group in groups],
        "missing_bundles": missing_bundles(granted),
        "sent": counts.get("CONFIRMED", 0), "pending": counts.get("PENDING", 0) + counts.get("DISPATCHING", 0)
        + counts.get("VERIFYING", 0) + counts.get("SUBMITTED", 0),
        "attention": sum(counts.get(name, 0) for name in ("FAILED", "UNCERTAIN", "BLOCKED_PERMISSION", "CONFLICT")),
        "last_sent_at": last,
    }


async def enable_all(session, connection, user_id: UUID) -> UUID | None:
    """Enable every available group the granted scopes allow and send what HercFit already has.

    Returns the history operation (None when no group could be enabled). Runs in the caller's
    transaction: the API request, or the OAuth callback after the user granted the scopes.
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
