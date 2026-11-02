"""/api/v2/health: phiên có chi tiết, chuỗi dày, bản ghi nguồn, insight và nhật ký cá nhân.

Phân trang bằng cursor ở mọi nơi; trợ lý cần consent thiết bị cho dữ liệu thiết bị
và consent nhạy cảm riêng cho nhật ký nhạy cảm (identity.consent).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select, tuple_

from api.dependencies import UserContextDep
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.analytics.services import coverage as coverage_service
from domains.health_records.models.device_records import DeviceWorkout, SleepSession
from domains.health_records.models.sources import HealthSeriesChunk, HealthSourceRecord
from domains.health_records.services import logs as log_service
from domains.identity import consent
from domains.shared.schemas.tracking import TimeZoneName

router = APIRouter(prefix="/health", tags=["health-data"], route_class=IdempotentRoute)
MAX_SERIES_DAYS = 7


def _cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        moment, item = value.split("|", 1)
        return datetime.fromisoformat(moment), UUID(item)
    except ValueError:
        raise HTTPException(422, "Invalid cursor") from None


def _next(items: list[Any], limit: int, time_field: str) -> str | None:
    if len(items) <= limit:
        return None
    last = items[limit - 1]
    return f"{getattr(last, time_field).isoformat()}|{last.id}"


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None


@router.get("/sessions", response_model=Page, summary="Phiên ngủ / buổi tập thiết bị kèm chi tiết")
async def sessions(service: UserContextDep, kind: Literal["sleep", "workout"], start_date: date, end_date: date,
                   cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    await consent.require_device_access(service.session, service.user_id)
    model, time_field = (SleepSession, "start_at") if kind == "sleep" else (DeviceWorkout, "started_at")
    column = getattr(model, time_field)
    query = select(model).where(model.user_id == service.user_id, model.is_active.is_(True),
                                model.local_date >= start_date, model.local_date <= end_date)
    after = _cursor(cursor)
    if after:
        query = query.where(tuple_(column, model.id) < after)
    rows = list((await service.session.execute(query.order_by(column.desc(), model.id.desc()).limit(limit + 1))).scalars())
    fields = [c.name for c in model.__table__.columns if c.name not in ("user_id",)]
    return Page(items=[{name: getattr(row, name) for name in fields} for row in rows[:limit]],
                next_cursor=_next(rows, limit, time_field))


@router.get("/sessions/{workout_id}/route", summary="Lộ trình GPS (TCX) của một buổi tập thiết bị",
            response_class=Response, responses={200: {"content": {"application/vnd.garmin.tcx+xml": {}}}})
async def workout_route(service: UserContextDep, workout_id: UUID):
    """File lộ trình của chính người dùng. Lộ trình không bao giờ được đưa cho trợ lý (không consent nào mở được)."""
    import zlib

    from core import principal as principals
    from domains.health_records.models.clinical import WorkoutRoute

    if principals.is_agent():
        raise HTTPException(403, "Routes are available to the user only")
    data = (await service.session.execute(select(WorkoutRoute.data_zlib).where(  # cột tải trễ: chọn nó tường minh
        WorkoutRoute.workout_id == workout_id, WorkoutRoute.user_id == service.user_id))).scalar_one_or_none()
    if data is None:
        raise HTTPException(404, "No route stored for this workout")
    return Response(zlib.decompress(data), media_type="application/vnd.garmin.tcx+xml",
                    headers={"Cache-Control": "private, no-store"})


@router.get("/series", summary="Chuỗi dày (nhịp tim, bước chân...) theo nguồn, có gộp theo độ phân giải")
async def series(service: UserContextDep, data_type: str, start: datetime, end: datetime,
                 resolution: Literal["raw", "minute", "hour"] = "minute"):
    await consent.require_device_access(service.session, service.user_id)
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise HTTPException(422, "start and end must be timezone-aware and ordered")
    if end - start > timedelta(days=MAX_SERIES_DAYS):
        raise HTTPException(422, f"At most {MAX_SERIES_DAYS} days per request")
    from domains.health_records import series as series_reader
    return await series_reader.window(service.session, service.user_id, data_type, start, end, resolution=resolution)


@router.get("/records", response_model=Page, summary="Bản ghi nguồn đã nhận từ nhà cung cấp")
async def records(service: UserContextDep, data_type: str, start_date: date, end_date: date,
                  cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    await consent.require_device_access(service.session, service.user_id)
    model = HealthSourceRecord
    query = select(model).where(model.user_id == service.user_id, model.data_type == data_type,
                                model.civil_date >= start_date, model.civil_date <= end_date)
    after = _cursor(cursor)
    if after:
        query = query.where(tuple_(model.fetched_at, model.id) < after)
    rows = list((await service.session.execute(query.order_by(model.fetched_at.desc(), model.id.desc())
                                               .limit(limit + 1))).scalars())
    from core import principal as principals
    agent = principals.is_agent()
    items = [{"id": row.id, "data_type": row.data_type, "resource_name": row.resource_name,
              "physical_start": row.physical_start, "physical_end": row.physical_end, "civil_date": row.civil_date,
              "utc_offset_s": row.utc_offset_s, "source_key": row.source_key, "data_source": row.data_source,
              "quality": row.quality, "unknown_paths": row.unknown_paths, "deletion_state": row.deletion_state,
              "schema_revision": row.schema_revision, "api_version": row.api_version,
              # Payload thô của nhà cung cấp (có thể chứa dạng sóng hoặc lộ trình) chỉ dành cho người dùng.
              **({} if agent else {"payload": row.payload})} for row in rows[:limit]]
    return Page(items=items, next_cursor=_next(rows, limit, "fetched_at"))


@router.get("/insights", summary="Phân tích có phương pháp: nền 28 ngày và độ phủ dữ liệu")
async def insights(service: UserContextDep, days: Annotated[int, Query(ge=7, le=90)] = 28,
                   end_date: date | None = None):
    await consent.require_device_access(service.session, service.user_id)
    end = end_date or datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    report = await coverage_service.coverage(service.session, service.user_id, start, end)
    baselines, obtained = await coverage_service.baselines_for(service.session, service.user_id, end, days)
    return {
        "start_date": start, "end_date": end,
        "baselines": [{"metric": b.metric, "label": coverage_service.BASELINE_METRICS[b.metric], "value": b.value,
                       "spread": b.spread, "n": b.n, "window_days": b.window_days, "as_of": b.as_of,
                       "method": ("median of observed days up to the end date" if obtained == "live" and b.as_of > end
                                  else "median of complete days before as_of"),
                       "obtained": obtained, "algorithm_version": b.algorithm_version} for b in baselines.values()],
        "coverage": {column: {key: value for key, value in entry.items() if key != "by_day"}
                     for column, entry in report.items()},
    }


# ------------------------------------------------------------------------------------------- nhật ký
LogKind = Literal["hydration", "nutrition", "symptoms", "mood", "menstrual-period", "ovulation-test"]


def _log(entity) -> dict[str, Any]:
    return {c.name: getattr(entity, c.name) for c in entity.__table__.columns if c.name != "user_id"}


@router.get("/logs/{kind}", response_model=Page, summary="Nhật ký sức khoẻ cá nhân")
async def list_logs(kind: LogKind, service: UserContextDep, start_date: date | None = None,
                    end_date: date | None = None, cursor: str | None = None,
                    limit: Annotated[int, Query(ge=1, le=100)] = 50):
    rows = await log_service.list_logs(service.session, service.user_id, kind, start=start_date, end=end_date,
                                       limit=limit + 1, cursor=_cursor(cursor))
    return Page(items=[_log(row) for row in rows[:limit]],
                next_cursor=_next(rows, limit, log_service.KINDS[kind]["time"]))


@router.post("/logs/{kind}:preview", summary="Xem trước tác động (cục bộ và Google) trước khi ghi")
async def preview_log(kind: LogKind, payload: dict[str, Any], service: UserContextDep):
    return await log_service.preview(service.session, service.user_id, kind, payload)


@router.post("/logs/{kind}", status_code=status.HTTP_201_CREATED, summary="Ghi nhật ký", response_model=dict[str, Any],
             description="Gửi kèm preview_sha256 từ /logs/{kind}:preview để ràng buộc lần ghi với đúng bản xem trước.")
@transaction
async def create_log(kind: LogKind, payload: dict[str, Any], service: UserContextDep):
    entity = await log_service.create(service.session, service.user_id, kind, payload)
    result = _log(entity)
    return result


class LogReplace(BaseModel):
    expected_version_id: int
    values: dict[str, Any]


@router.patch("/logs/{kind}/{log_id}", summary="Sửa nhật ký (cần phiên bản hiện tại)", response_model=dict[str, Any])
@transaction
async def replace_log(kind: LogKind, log_id: UUID, payload: LogReplace, service: UserContextDep):
    entity = await log_service.replace(service.session, service.user_id, kind, log_id, payload.values,
                                       payload.expected_version_id)
    result = _log(entity)
    return result


@router.delete("/logs/{kind}/{log_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xoá nhật ký")
@transaction
async def delete_log(kind: LogKind, log_id: UUID, service: UserContextDep,
                     expected_version_id: Annotated[int, Query(ge=1)], remote: bool = False):
    # remote=true xoá cả bản HercFit đã xuất lên Google (lựa chọn tường minh của người dùng).
    await log_service.delete(service.session, service.user_id, kind, log_id, expected_version_id, remote=remote)
    return Response(status_code=204)
