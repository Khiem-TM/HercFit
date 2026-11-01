"""Bản cài đặt của Google Health cho các port nhà cung cấp của miền health-records."""
from __future__ import annotations

from uuid import UUID

from domains.health_records import ports
from domains.health_records.schemas.health import HEALTH_PROVIDER
from integrations.google_health.models import HealthConnection


class GoogleHealthDirectory:
    async def status(self, session, user_id: UUID) -> ports.ProviderStatus | None:
        connection = await HealthConnection.for_user(session, user_id)
        if connection is None:
            return None
        return ports.ProviderStatus(provider=HEALTH_PROVIDER, status=connection.status,
                                    provider_profile=dict(connection.provider_profile or {}),
                                    last_success_at=connection.last_success_at)

    async def availability(self, session, user_id: UUID) -> dict[str, ports.TypeAvailability]:
        from datetime import date

        from sqlalchemy import text

        from core.settings import settings
        from integrations.google_health.contract import scopes
        from integrations.google_health.contract.registry import DATA_TYPES, Op, runtime_enabled

        connection = await HealthConnection.for_user(session, user_id)
        if connection is None:
            return {}
        granted = list(connection.granted_scopes or [])
        cursors = {row[0]: row[1] for row in (await session.execute(text(
            "SELECT data_type, complete_through FROM sync_cursors WHERE connection_id = :c"),
            {"c": connection.id})).all()}
        legacy = (connection.sync_cursor or {}).get("types") or {}
        result = {}
        for data_type, item in DATA_TYPES.items():
            if not item.readable:
                continue
            op = Op.LIST if Op.LIST in item.read_ops else Op.DAILY_ROLLUP
            through = cursors.get(data_type)
            if through is None and (legacy.get(data_type) or {}).get("complete_through"):
                through = date.fromisoformat(legacy[data_type]["complete_through"])
            result[data_type] = ports.TypeAvailability(
                granted=scopes.can_read(item.scope_group, granted),
                enabled=runtime_enabled(data_type, op, verified=settings.verified_capabilities,
                                        api_version=item.api_versions[0]),
                complete_through=through)
        return result

    async def before_account_erasure(self, session, user_id: UUID) -> None:
        from integrations.google_health.connection import revoke_connection

        connection = await HealthConnection.for_user(session, user_id)
        if connection is not None:
            await revoke_connection(connection)


ports.register(GoogleHealthDirectory())


def _register_export_hook() -> None:
    from domains.shared import write_hooks
    from integrations.google_health.export import capture

    write_hooks.register(capture.hook)
    write_hooks.register_previewer(capture.preview)


_register_export_hook()
