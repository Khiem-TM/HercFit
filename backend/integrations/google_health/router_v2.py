"""/api/v2/integrations/google-health: khả năng, scope, job đồng bộ (202 + operation).

Thiết lập xuất và xung đột được thêm ở M6; endpoint webhook nằm trong webhook.py.
"""
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from api.dependencies import service_dependency
from core.jobs import queue
from core.rate_limit import SlidingWindowLimiter, enforce
from core.settings import settings
from domains.shared import operations
from integrations.google_health.connection import HealthConnectionService
from integrations.google_health.contract import scopes as contract_scopes
from integrations.google_health.contract.registry import DATA_TYPES, DISCOVERY_REVISION, Op, runtime_enabled
from integrations.google_health.router import COOKIE_PATH, _set_cookie
from integrations.google_health import oauth

router = APIRouter(prefix="/integrations/google-health", tags=["integrations"])
ServiceDep = Annotated[HealthConnectionService, service_dependency(HealthConnectionService)]
_limiter = SlidingWindowLimiter(6)


class CapabilityRead(BaseModel):
    data_type: str
    kind: str
    scope_group: str
    family: str
    read: list[str]
    write: list[str]
    webhook: bool
    sensitive: bool
    verification: str
    api_version: str | None = None
    beta: bool = False
    granted: bool
    enabled: bool
    cursor: dict[str, Any] | None = None


class CapabilitiesRead(BaseModel):
    discovery_revision: str
    ingest_mode: str
    capabilities: list[CapabilityRead]


class ScopesRead(BaseModel):
    granted: list[str]
    bundles: list[dict[str, Any]]


class ScopesRequest(BaseModel):
    bundles: list[str] = Field(min_length=1, max_length=len(contract_scopes.BUNDLES))


class AuthorizationRead(BaseModel):
    authorization_url: str


class SyncAccepted(BaseModel):
    operation_id: UUID
    detail: str


class JobRead(BaseModel):
    id: UUID
    kind: str
    data_type: str | None
    state: str
    window_start: Any = None
    window_end: Any = None
    attempts: int
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class JobPage(BaseModel):
    items: list[JobRead]
    next_cursor: str | None


async def _connection(service: HealthConnectionService):
    connection = await service.connection()
    if connection is None:
        raise HTTPException(404, "Chưa kết nối Google Health")
    return connection


@router.get("/capabilities", response_model=CapabilitiesRead, summary="Khả năng theo từng loại dữ liệu")
async def capabilities(service: ServiceDep):
    connection = await service.connection()
    granted = list(connection.granted_scopes or []) if connection else []
    cursors = {}
    if connection is not None:
        rows = (await service.session.execute(text(
            "SELECT data_type, complete_through, earliest_complete, status, error_code, updated_at FROM sync_cursors "
            "WHERE connection_id = :c"), {"c": connection.id})).mappings().all()
        cursors = {row["data_type"]: dict(row) for row in rows}
    items = []
    from integrations.google_health.adapters import api_version_for

    for item in sorted(DATA_TYPES.values(), key=lambda spec: spec.id):
        op = Op.LIST if Op.LIST in item.read_ops else Op.DAILY_ROLLUP
        version = api_version_for(item.id, set(settings.GH_V4BETA_TYPES))
        has_scope = (contract_scopes.can_read(item.scope_group, granted) if item.readable
                     else contract_scopes.can_write(item.scope_group, granted))
        items.append(CapabilityRead(
            data_type=item.id, kind=item.kind.value, scope_group=item.scope_group, family=item.family,
            read=sorted(op.value for op in item.read_ops), write=sorted(op.value for op in item.write_ops),
            webhook=item.webhook, sensitive=item.sensitivity.value == "sensitive",
            verification=item.verification.value, granted=has_scope, api_version=version or None,
            beta=version == "v4beta",
            enabled=bool(version) and item.readable and runtime_enabled(
                item.id, op, verified=settings.verified_capabilities, api_version=version),
            cursor={key: value for key, value in cursors[item.id].items() if key != "data_type"}
            if item.id in cursors else None))
    return CapabilitiesRead(discovery_revision=DISCOVERY_REVISION, ingest_mode=settings.GH_INGEST_V2,
                            capabilities=items)


class PairedDeviceRead(BaseModel):
    device_type: str | None
    device_version: str | None
    battery_level: int | None
    battery_status: str | None
    last_sync_at: datetime | None


class DataSourceRead(BaseModel):
    source_key: str
    platform: str | None
    recording_method: str | None
    device: str | None
    application: str | None
    data_types: list[str]
    records: int
    last_measured_at: datetime | None


class DevicesRead(BaseModel):
    devices: list[PairedDeviceRead]
    sources: list[DataSourceRead]


@router.get("/devices", response_model=DevicesRead, summary="Thiết bị đã ghép và nguồn ghi dữ liệu")
async def devices(service: ServiceDep):
    """Thiết bị đã ghép (pairedDevices của Google) và các nguồn ghi thấy trong bản ghi đã nhận.

    Các nguồn được giữ tách biệt (không gộp giữa các nguồn); `source_key` là cùng khoá mờ mà
    chuỗi và bản ghi mang theo. Chỉ nhãn và số đếm: không có giá trị đo.
    """
    from domains.identity import consent

    await consent.require_device_access(service.session, service.user_id)
    connection = await service.connection()
    if connection is None:
        return DevicesRead(devices=[], sources=[])
    paired = (await service.session.execute(text("""
        SELECT device_type, device_version, battery_level, battery_status, last_sync_at FROM paired_devices
        WHERE connection_id = :c AND is_active ORDER BY last_sync_at DESC NULLS LAST"""),
        {"c": connection.id})).mappings().all()
    sources = (await service.session.execute(text("""
        SELECT source_key, data_source->>'platform' AS platform, data_source->>'recordingMethod' AS recording_method,
               NULLIF(concat_ws(' ', data_source->'device'->>'manufacturer', data_source->'device'->>'displayName'), '') AS device,
               data_source->'application'->>'packageName' AS application,
               array_agg(DISTINCT data_type ORDER BY data_type) AS data_types, count(*) AS records,
               max(COALESCE(physical_end, physical_start)) AS last_measured_at
        FROM health_source_records WHERE connection_id = :c AND deletion_state = 'PRESENT'
        GROUP BY 1, 2, 3, 4, 5 ORDER BY records DESC LIMIT 50"""), {"c": connection.id})).mappings().all()
    return DevicesRead(devices=[PairedDeviceRead(**row) for row in paired],
                       sources=[DataSourceRead(**row) for row in sources])


@router.get("/scopes", response_model=ScopesRead, summary="Quyền Google đã cấp theo nhóm tính năng")
async def get_scopes(service: ServiceDep):
    connection = await service.connection()
    granted = list(connection.granted_scopes or []) if connection else []
    owned = set(contract_scopes.granted_bundles(granted))
    return ScopesRead(granted=granted, bundles=[
        {"key": bundle.key, "label": bundle.label_vi, "sensitive": bundle.sensitive, "granted": bundle.key in owned,
         "scopes": list(bundle.scopes)} for bundle in contract_scopes.BUNDLES.values()])


@router.post("/scopes", response_model=AuthorizationRead, summary="Xin thêm quyền (uỷ quyền tăng dần)")
async def request_scopes(payload: ScopesRequest, service: ServiceDep, response: Response):
    unknown = [key for key in payload.bundles if key not in contract_scopes.BUNDLES]
    if unknown:
        raise HTTPException(422, f"Unknown bundles: {', '.join(unknown)}")
    enforce(_limiter, f"scopes:{service.user_id}")
    url, nonce, verifier = service.start(None, scopes=contract_scopes.bundle_scopes(payload.bundles))
    _set_cookie(response, oauth.NONCE_COOKIE, nonce)
    _set_cookie(response, oauth.PKCE_COOKIE, verifier)
    return AuthorizationRead(authorization_url=url)


@router.post("/sync-jobs", status_code=status.HTTP_202_ACCEPTED, response_model=SyncAccepted,
             summary="Đồng bộ ngay (tạo công việc, theo dõi qua /operations/{id})")
async def create_sync(service: ServiceDep):
    enforce(_limiter, f"sync:{service.user_id}")
    connection = await _connection(service)
    if connection.status != "ACTIVE":
        raise HTTPException(409, "Kết nối Google Health không ở trạng thái hoạt động; hãy kết nối lại.")
    operation_id = await operations.create(service.session, service.user_id, "health.sync")
    kind = "GH_LEGACY_SYNC" if settings.GH_INGEST_V2 == "off" else "GH_RECONCILE"
    await queue.enqueue(service.session, kind, user_id=service.user_id, connection_id=connection.id,
                        connection_generation=connection.generation, operation_id=operation_id, priority=90,
                        dedupe_key=f"manual:{connection.id}", payload={"reason": "manual"})
    await service.session.commit()
    return SyncAccepted(operation_id=operation_id, detail="Đã xếp lịch đồng bộ Google Health.")


@router.get("/sync-jobs", response_model=JobPage, summary="Lịch sử công việc đồng bộ (phân trang theo con trỏ)")
async def list_jobs(service: ServiceDep, cursor: str | None = None,
                    limit: Annotated[int, Query(ge=1, le=100)] = 50):
    connection = await _connection(service)
    params: dict[str, Any] = {"c": connection.id, "limit": limit + 1}
    where = ""
    if cursor:
        try:
            created, job_id = cursor.split("|", 1)
            params.update(created=datetime.fromisoformat(created), job=UUID(job_id))
        except ValueError:
            raise HTTPException(422, "Invalid cursor") from None
        where = "AND (created_at, id) < (:created, :job)"
    rows = (await service.session.execute(text(f"""
        SELECT id, kind, data_type, state, window_start, window_end, attempts, error_code, created_at, finished_at
        FROM jobs WHERE connection_id = :c {where} ORDER BY created_at DESC, id DESC LIMIT :limit"""),
        params)).mappings().all()
    items = [JobRead(**row) for row in rows[:limit]]
    next_cursor = f"{items[-1].created_at.isoformat()}|{items[-1].id}" if len(rows) > limit else None
    return JobPage(items=items, next_cursor=next_cursor)


__all__ = ["router", "COOKIE_PATH"]


# ------------------------------------------------------------------------------------------- xuất (M6)
from integrations.google_health.contract.registry import EXPORT_GROUPS, EXPORT_ROLLOUT, Op as _Op, spec as _spec  # noqa: E402


class ExportGroupRead(BaseModel):
    group: str
    label: str
    data_types: list[str]
    enabled: bool
    enabled_at: datetime | None
    write_scope_granted: bool
    verified: bool
    rolled_out: bool
    bundle: str


class ExportSettingsUpdate(BaseModel):
    group: str
    enabled: bool


GROUP_LABELS = {"body": "Chỉ số cơ thể", "hydration": "Nước uống", "nutrition": "Dinh dưỡng", "workout": "Buổi tập",
                "sleep": "Giấc ngủ", "symptoms": "Triệu chứng", "mood": "Tâm trạng", "reproductive": "Sức khoẻ sinh sản"}


async def _export_groups(service: HealthConnectionService) -> list[ExportGroupRead]:
    connection = await _connection(service)
    granted = list(connection.granted_scopes or [])
    rows = {row.export_group: row for row in (await service.session.execute(text(
        "SELECT export_group, enabled, enabled_at FROM google_export_settings WHERE connection_id = :c"),
        {"c": connection.id})).all()}
    result = []
    for group in EXPORT_ROLLOUT:
        types = list(EXPORT_GROUPS[group])
        row = rows.get(group)
        result.append(ExportGroupRead(
            group=group, label=GROUP_LABELS[group], data_types=types, enabled=bool(row and row.enabled),
            enabled_at=row.enabled_at if row else None,
            write_scope_granted=all(contract_scopes.can_write(_spec(t).scope_group, granted) for t in types),
            verified=all(runtime_enabled(t, _Op.CREATE, verified=settings.verified_capabilities) for t in types),
            rolled_out=group in settings.GH_EXPORT_GROUPS, bundle=contract_scopes.EXPORT_GROUP_BUNDLES[group]))
    return result


@router.get("/export-settings", response_model=list[ExportGroupRead], summary="Xuất dữ liệu lên Google theo nhóm")
async def get_export_settings(service: ServiceDep):
    return await _export_groups(service)


@router.put("/export-settings", response_model=list[ExportGroupRead], summary="Bật/tắt xuất một nhóm dữ liệu",
            description="Bật chỉ xuất các thay đổi từ thời điểm này; muốn gửi dữ liệu cũ hãy gọi xuất lịch sử. "
                        "Cần quyền ghi tương ứng (POST /scopes với bundle của nhóm).")
async def put_export_settings(payload: ExportSettingsUpdate, service: ServiceDep):
    if payload.group not in EXPORT_GROUPS:
        raise HTTPException(422, "Unknown export group")
    connection = await _connection(service)
    groups = {item.group: item for item in await _export_groups(service)}
    if payload.enabled and not groups[payload.group].write_scope_granted:
        raise HTTPException(409, {"code": "write_scope_required", "bundle": groups[payload.group].bundle,
                                  "message": "Cần cấp quyền ghi cho nhóm này trước."})
    await service.session.execute(text("""
        INSERT INTO google_export_settings (connection_id, export_group, enabled, enabled_at, updated_at)
        VALUES (:c, :g, :enabled, CASE WHEN :enabled THEN now() END, now())
        ON CONFLICT (connection_id, export_group) DO UPDATE SET enabled = EXCLUDED.enabled,
            enabled_at = CASE WHEN EXCLUDED.enabled AND NOT google_export_settings.enabled THEN now()
                              WHEN EXCLUDED.enabled THEN google_export_settings.enabled_at END,
            updated_at = now()"""), {"c": connection.id, "g": payload.group, "enabled": payload.enabled})
    await service.session.commit()
    return await _export_groups(service)


@router.post("/export-settings/{group}:history", status_code=status.HTTP_202_ACCEPTED, response_model=SyncAccepted,
             summary="Xuất dữ liệu cũ của nhóm (theo yêu cầu người dùng)")
async def export_history(group: str, service: ServiceDep):
    groups = {item.group: item for item in await _export_groups(service)}
    if group not in groups or not groups[group].enabled:
        raise HTTPException(409, "Bật xuất nhóm này trước")
    connection = await _connection(service)
    operation_id = await operations.create(service.session, service.user_id, "health.history_export", {"group": group})
    await queue.enqueue(service.session, "GH_HISTORY_EXPORT", queue="export", user_id=service.user_id,
                        connection_id=connection.id, connection_generation=connection.generation,
                        operation_id=operation_id, dedupe_key=f"history:{connection.id}:{group}",
                        payload={"group": group}, priority=20)
    await service.session.execute(text("UPDATE google_export_settings SET history_operation_id = :o "
                                       "WHERE connection_id = :c AND export_group = :g"),
                                  {"o": operation_id, "c": connection.id, "g": group})
    await service.session.commit()
    return SyncAccepted(operation_id=operation_id, detail="Đã xếp lịch xuất dữ liệu cũ.")


class ExportSwitchGroup(BaseModel):
    group: str
    label: str
    enabled: bool
    write_scope_granted: bool


class ExportSwitchRead(BaseModel):
    available: bool
    enabled: bool
    partial: bool
    groups: list[ExportSwitchGroup]
    missing_bundles: list[str]
    sent: int
    pending: int
    attention: int
    last_sent_at: datetime | None
    authorization_url: str | None = None
    operation_id: UUID | None = None


class ExportSwitchUpdate(BaseModel):
    enabled: bool


@router.get("/export", response_model=ExportSwitchRead, summary="Đồng bộ HercFit lên Google Health (một công tắc)")
async def get_export(service: ServiceDep):
    from integrations.google_health.export import switch
    return ExportSwitchRead(**await switch.state(service.session, await _connection(service)))


@router.put("/export", response_model=ExportSwitchRead, summary="Bật/tắt đồng bộ lên Google Health",
            description="Bật: mọi nhóm đã mở được bật và dữ liệu hiện có được gửi một lần. Nếu còn thiếu quyền Google, "
                        "trả `authorization_url` (một màn hình đồng ý cho mọi quyền còn thiếu); callback bật nốt sau khi "
                        "người dùng cấp quyền. Tắt: ngừng gửi; dữ liệu đã có trên Google được giữ nguyên.")
async def put_export(payload: ExportSwitchUpdate, service: ServiceDep, response: Response):
    from integrations.google_health.export import switch
    connection = await _connection(service)
    url = operation_id = None
    if not payload.enabled:
        await switch.disable_all(service.session, connection)
    else:
        if not switch.available_groups():
            raise HTTPException(409, {"code": "export_unavailable", "message": "Đồng bộ lên Google chưa được mở."})
        missing = switch.missing_bundles(list(connection.granted_scopes or []))
        if missing:
            enforce(_limiter, f"scopes:{service.user_id}")
            url, nonce, verifier = service.start(None, scopes=contract_scopes.bundle_scopes(missing), then=switch.INTENT)
            _set_cookie(response, oauth.NONCE_COOKIE, nonce)
            _set_cookie(response, oauth.PKCE_COOKIE, verifier)
        else:
            operation_id = await switch.enable_all(service.session, connection, service.user_id)
    await service.session.commit()
    current = await switch.state(service.session, connection)
    return ExportSwitchRead(**current, authorization_url=url, operation_id=operation_id)


class ConflictRead(BaseModel):
    id: UUID
    data_type: str
    aggregate_type: str
    aggregate_id: UUID
    local_payload: dict[str, Any]
    remote_payload: dict[str, Any] | None
    detected_at: datetime


class ConflictResolution(BaseModel):
    resolution: str = Field(pattern="^(KEEP_LOCAL|ACCEPT_REMOTE)$")


@router.get("/conflicts", response_model=list[ConflictRead], summary="Xung đột giữa bản HercFit và bản trên Google")
async def list_conflicts(service: ServiceDep):
    rows = (await service.session.execute(text("""
        SELECT x.id, m.data_type, m.aggregate_type, m.aggregate_id, x.local_payload, x.remote_payload, x.detected_at
        FROM export_conflicts x JOIN google_resource_mappings m ON m.id = x.mapping_id
        WHERE x.user_id = :u AND x.resolution IS NULL ORDER BY x.detected_at"""), {"u": service.user_id})).mappings().all()
    return [ConflictRead(**row) for row in rows]


@router.post("/conflicts/{conflict_id}:resolve", response_model=ConflictRead, summary="Chọn giữ bản HercFit hoặc nhận bản Google")
async def resolve_conflict(conflict_id: UUID, payload: ConflictResolution, service: ServiceDep):
    from integrations.google_health.export.conflicts import resolve
    return await resolve(service.session, service.user_id, conflict_id, payload.resolution)
