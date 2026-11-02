"""Schema của kết nối Google Health và các lệnh ghi xuyên qua."""
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel

from domains.health_records.schemas.health import HEALTH_PROVIDER, ConnectionStatus
from domains.shared.schemas.common import InputSchema


class HealthConnectRequest(InputSchema):
    share_with_assistant: bool = True


class HealthConnectResponse(BaseModel):
    authorization_url: str


class HealthConsentUpdate(InputSchema):
    share_with_assistant: bool
    share_sensitive_with_assistant: bool | None = None


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
    # Do Google báo: tuổi, chiều dài sải chân và cài đặt đơn vị.
    provider_profile: dict[str, Any] = {}
    last_sync_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    last_error_code: str | None = None
    # Số điểm đang lưu theo loại, và trạng thái đọc từng loại {from, through, error}.
    records: dict[str, int] = {}
    types: dict[str, Any] = {}


class HealthSyncAccepted(BaseModel):
    status: Literal["accepted", "running"] = "accepted"
    detail: str


class HealthRecordRead(BaseModel):
    """Một điểm Google do HercFit ghi xuyên qua (buổi thể thao, cân nặng, nước...)."""
    id: Any = None
    data_type: str
    local_date: Any = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    value: dict[str, Any] = {}
    written_by_hercfit: bool = True
    pending: bool = False
    derived: dict[str, Any] = {}
