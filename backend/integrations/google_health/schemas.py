"""Dữ liệu sức khoẻ từ thiết bị đeo (Google Health API) và hồ sơ sức khoẻ hợp nhất.

Tách ra từ schemas.health trong đợt tổ chức lại theo miền."""
from datetime import date
from typing import Any, Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel
from domains.shared.schemas.common import InputSchema, ReadSchema
from domains.health_records.schemas.health import ConnectionStatus, HEALTH_PROVIDER, SyncStatus, SyncTrigger


# ---------------------------------------------------------------------------
# Kết nối và đồng bộ
# ---------------------------------------------------------------------------
class HealthConnectRequest(InputSchema):
    share_with_assistant: bool = True

class HealthConnectResponse(BaseModel):
    authorization_url: str

class HealthConsentUpdate(InputSchema):
    share_with_assistant: bool
    share_sensitive_with_assistant: bool | None = None

class HealthSyncRunRead(ReadSchema):
    id: UUID
    trigger: SyncTrigger
    status: SyncStatus
    created_at: AwareDatetime
    finished_at: AwareDatetime | None
    window_start: date | None
    window_end: date | None
    counts: dict[str, Any]
    error_code: str | None

class HealthConnectionRead(BaseModel):
    provider: str = HEALTH_PROVIDER
    configured: bool
    connected: bool
    status: ConnectionStatus | None = None
    account_email: str | None = None
    granted_scopes: list[str] = []
    missing_scopes: list[str] = []
    share_with_assistant: bool = False
    share_sensitive_with_assistant: bool = False
    consented_at: AwareDatetime | None = None
    timezone: str | None = None
    # Do nhà cung cấp báo: tuổi, membership_start_date, chiều dài sải chân và cài đặt đơn vị.
    provider_profile: dict[str, Any] = {}
    last_sync_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    next_sync_at: AwareDatetime | None = None
    last_error_code: str | None = None
    records: dict[str, int] = {}
    last_run: HealthSyncRunRead | None = None

class HealthSyncAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"
    detail: str
