"""Ghi xuyên qua (write-through) cho dữ liệu Google sở hữu: buổi thể thao, cân nặng, chiều cao, % mỡ, nước, giấc ngủ.

HercFit không giữ bản riêng của các dữ liệu này: lệnh ghi đi thẳng lên Google, điểm Google trả về
được lưu ngay vào health_points (đọc lại thấy ngay), và lần reconcile sau thay thế nó bằng bản của
Google. Chỉ sửa / xoá được điểm do HercFit ghi; điểm của thiết bị thuộc về thiết bị.

Buổi thể thao nhận đúng đầu vào của một mục buổi tập (bài trong catalog + performance), nên ước
tính kcal và quãng đường dùng lại đúng công thức MET / ACSM của buổi tập (build_exercise_item).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from domains.catalog.schemas.exercises import ExercisePerformance
from domains.health_records.models.health_points import HealthPoint
from domains.health_records.types import can_write, spec
from domains.shared.models.activity import build_exercise_item
from domains.training.schemas.trainings import GYM_GENERAL_CODE
from domains.shared.schemas.common import InputSchema
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName
from integrations.google_health import kinds, tokens
from integrations.google_health.client import PERMISSION, GoogleHealthClient, GoogleHealthError, ReauthRequired
from integrations.google_health.models import HealthConnection

Kind = Literal["exercise", "weight", "height", "body-fat", "hydration", "sleep"]
DATA_TYPE = {"exercise": "exercise", "weight": "weight", "height": "height", "body-fat": "body-fat",
             "hydration": "hydration-log", "sleep": "sleep"}
# Giấc ngủ ghi tay: một đêm hợp lý và gần đây (đồng hồ vẫn là nguồn chính khi có).
SLEEP_MIN, SLEEP_MAX, SLEEP_MAX_AGE = timedelta(hours=1), timedelta(hours=16), timedelta(days=30)
# Môn trong catalog (configuration.sport / activity) → ExerciseType của Google; không khớp thì SPORT.
SPORT_TYPES = {"badminton": "BADMINTON", "basketball": "BASKETBALL", "football": "SOCCER", "soccer": "SOCCER",
               "pickleball": "PICKELBALL", "tennis": "TENNIS", "table_tennis": "TABLE_TENNIS",
               "volleyball": "VOLLEYBALL", "swimming": "SWIMMING", "yoga": "YOGA", "boxing": "BOXING",
               "resistance_training": "STRENGTH_TRAINING"}
ACTIVITY_TYPES = {"RUN": "RUNNING", "WALK": "WALKING", "CYCLE": "BIKING", "SWIM": "SWIMMING_POOL", "HIKE": "HIKING",
                  "ROW": "ROWING_MACHINE"}


http_client = httpx.AsyncClient  # test thay bằng client có MockTransport


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SportInput(InputSchema):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    started_at: AwareDatetime
    exercise_id: UUID
    performance: ExercisePerformance
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: Annotated[str | None, Field(max_length=1000)] = None


class MeasurementInput(InputSchema):
    value: Annotated[float, Field(gt=0, le=1000)]   # kg, cm hoặc %
    measured_at: AwareDatetime = Field(default_factory=_now)
    timezone: TimeZoneName = DEFAULT_TIMEZONE


class HydrationInput(InputSchema):
    amount_ml: Annotated[float, Field(gt=0, le=10_000)]
    consumed_at: AwareDatetime = Field(default_factory=_now)
    timezone: TimeZoneName = DEFAULT_TIMEZONE


class SleepInput(InputSchema):
    started_at: AwareDatetime   # giờ đi ngủ
    ended_at: AwareDatetime     # giờ thức dậy
    timezone: TimeZoneName = DEFAULT_TIMEZONE

    @model_validator(mode="after")
    def _plausible(self):
        span = self.ended_at - self.started_at
        if not SLEEP_MIN <= span <= SLEEP_MAX:
            raise ValueError("Giấc ngủ phải dài từ 1 đến 16 giờ (giờ dậy sau giờ đi ngủ).")
        now = _now()
        if self.ended_at > now + timedelta(minutes=5):
            raise ValueError("Giờ thức dậy không được ở tương lai.")
        if self.ended_at < now - SLEEP_MAX_AGE:
            raise ValueError("Chỉ ghi được giấc ngủ trong 30 ngày gần nhất.")
        return self


SCHEMAS = {"exercise": SportInput, "weight": MeasurementInput, "height": MeasurementInput,
           "body-fat": MeasurementInput, "hydration": HydrationInput, "sleep": SleepInput}


def exercise_type(snapshot: dict[str, Any]) -> str:
    configuration = snapshot.get("configuration") or {}
    sport = str(configuration.get("sport") or "").lower()
    return SPORT_TYPES.get(sport) or ACTIVITY_TYPES.get(str(configuration.get("activity") or "").upper()) or "SPORT"


async def _bodyweight(session, user_id: UUID) -> float | None:
    from domains.body.models.body_metrics import BodyMetric

    latest = await BodyMetric.get_latest_for_user(session, user_id=user_id, respect_consent=False)
    return float(latest.weight_kg) if latest is not None and latest.weight_kg is not None else None


async def _no_device_sleep(session, user_id: UUID, start: datetime, end: datetime, *, exclude: UUID | None) -> None:
    """Đêm thiết bị đã ghi thì không ghi tay chồng lên (Google sẽ có hai giấc ngủ cho cùng một đêm)."""
    query = select(HealthPoint.id, HealthPoint.written_by_hercfit).where(
        HealthPoint.user_id == user_id, HealthPoint.data_type == "sleep",
        HealthPoint.start_at < end, HealthPoint.end_at > start)
    for point_id, ours in (await session.execute(query)).all():
        if point_id == exclude:
            continue
        raise HTTPException(409, {"code": "device_sleep_exists" if not ours else "sleep_exists",
                                  "message": "Thiết bị đã ghi giấc ngủ cho khoảng giờ này." if not ours
                                  else "Đã có giấc ngủ ghi tay trùng khoảng giờ này; hãy sửa bản đó."})


async def build(session, user_id: UUID, kind: str, payload: dict[str, Any], *,
                exclude: UUID | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(DataPoint gửi lên Google, các giá trị HercFit đã suy ra để hiển thị trên thẻ xác nhận)."""
    data = SCHEMAS[kind].model_validate(payload)
    if isinstance(data, SportInput):
        item = await build_exercise_item(session, user_id, {"exercise_id": data.exercise_id,
                                                            "performance": data.performance.model_dump(mode="json")},
                                         bodyweight_kg=await _bodyweight(session, user_id))
        if item["kind"] == "STRENGTH" or item["exercise_snapshot"].get("code") == GYM_GENERAL_CODE:
            raise HTTPException(422, "Buổi gym được ghi bằng create_trainings (HercFit lưu và đẩy lên Google).")
        seconds = float(item["duration_seconds"] or data.performance.duration_seconds)
        kcal = float(item["energy_kcal"]) if item["energy_kcal"] is not None else None
        distance = float(item["distance_meters"]) if item["distance_meters"] is not None else None
        google_type = exercise_type(item["exercise_snapshot"])
        point = kinds.Session.build_exercise(
            start=data.started_at, end=data.started_at + timedelta(seconds=seconds), zone=data.timezone,
            exercise_type=google_type, name=data.name, active_seconds=seconds, kcal=kcal, distance_m=distance,
            notes=data.note)
        return point, {"exercise_type": google_type, "duration_seconds": seconds, "energy_kcal": kcal,
                       "distance_m": distance, "calorie_estimate": item["calorie_estimate"]}
    if isinstance(data, HydrationInput):
        return kinds.Session.build_hydration(moment=data.consumed_at, zone=data.timezone,
                                             milliliters=data.amount_ml), {"amount_ml": data.amount_ml}
    if isinstance(data, SleepInput):
        await _no_device_sleep(session, user_id, data.started_at, data.ended_at, exclude=exclude)
        minutes = round((data.ended_at - data.started_at).total_seconds() / 60)
        return kinds.Session.build_sleep(start=data.started_at, end=data.ended_at, zone=data.timezone), {
            "minutes_in_bed": minutes, "manual": True}
    point = kinds.Sample.build(DATA_TYPE[kind], moment=data.measured_at, zone=data.timezone, value=data.value)
    return point, {"value": data.value}


async def _client(session, user_id: UUID, data_type: str, http: httpx.AsyncClient) -> GoogleHealthClient:
    connection = await HealthConnection.for_user(session, user_id)
    if connection is None or connection.status != "ACTIVE":
        raise HTTPException(409, {"code": "google_health_required",
                                  "message": "Cần kết nối Google Health để ghi dữ liệu này."})
    try:
        token, granted = await tokens.access_token(connection.id, http)
    except ReauthRequired:
        await tokens.mark_reauth(connection.id)
        raise HTTPException(409, {"code": "google_health_reauth",
                                  "message": "Kết nối Google Health đã hết hạn; hãy kết nối lại."}) from None
    if not can_write(data_type, granted):
        raise HTTPException(403, {"code": "write_scope_missing",
                                  "message": "Chưa cấp quyền ghi dữ liệu này lên Google Health; hãy kết nối lại."})
    return GoogleHealthClient(token, http)


def view(point: HealthPoint) -> dict[str, Any]:
    return {"id": point.id, "data_type": point.data_type, "local_date": point.local_date, "start_at": point.start_at,
            "end_at": point.end_at, "value": point.value, "written_by_hercfit": point.written_by_hercfit}


async def _store(session, user_id: UUID, data_type: str, operation: dict[str, Any], zone: str) -> HealthPoint | None:
    """Lưu điểm Google vừa trả về; Operation chưa xong thì lần reconcile sau sẽ mang nó về."""
    response = operation.get("response") if operation.get("done") else None
    point = kinds.parse(spec(data_type), response, zone) if isinstance(response, dict) else None
    if point is None:
        return None
    [point_id] = await HealthPoint.upsert(session, [point.row(user_id, written_by_hercfit=True)])
    return await session.get(HealthPoint, point_id, populate_existing=True)


async def _owned(session, user_id: UUID, kind: str, point_id: UUID) -> HealthPoint:
    point = await session.get(HealthPoint, point_id)
    if point is None or point.user_id != user_id or point.data_type != DATA_TYPE[kind]:
        raise HTTPException(404, "Không tìm thấy bản ghi")
    if not point.written_by_hercfit:
        raise HTTPException(409, {"code": "device_record",
                                  "message": "Bản ghi do thiết bị ghi nên không sửa được; hãy ghi một bản mới."})
    return point


def _google_error(exc: GoogleHealthError) -> HTTPException:
    if exc.error_class == PERMISSION:
        return HTTPException(403, {"code": "write_scope_missing", "message": "Google Health từ chối quyền ghi."})
    return HTTPException(502, {"code": exc.code, "message": "Google Health chưa nhận lệnh ghi; hãy thử lại."})


async def create(session, user_id: UUID, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    data_type = DATA_TYPE[kind]
    point, derived = await build(session, user_id, kind, payload)
    async with http_client() as http:
        client = await _client(session, user_id, data_type, http)
        try:
            operation = await client.create_point(data_type, point)
        except GoogleHealthError as exc:
            raise _google_error(exc) from None
    stored = await _store(session, user_id, data_type, operation, payload.get("timezone") or DEFAULT_TIMEZONE)
    return {**(view(stored) if stored else {"data_type": data_type, "pending": True}), "derived": derived}


async def update(session, user_id: UUID, kind: str, point_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    data_type = DATA_TYPE[kind]
    current = await _owned(session, user_id, kind, point_id)
    point, derived = await build(session, user_id, kind, payload, exclude=current.id)
    async with http_client() as http:
        client = await _client(session, user_id, data_type, http)
        try:
            operation = await client.patch_point(current.remote_name, point)
        except GoogleHealthError as exc:
            raise _google_error(exc) from None
    stored = await _store(session, user_id, data_type, operation, payload.get("timezone") or DEFAULT_TIMEZONE)
    return {**view(stored or current), "derived": derived}


async def delete(session, user_id: UUID, kind: str, point_id: UUID) -> None:
    data_type = DATA_TYPE[kind]
    current = await _owned(session, user_id, kind, point_id)
    async with http_client() as http:
        client = await _client(session, user_id, data_type, http)
        try:
            await client.batch_delete(data_type, [current.remote_name])
        except GoogleHealthError as exc:
            if exc.status != 404:
                raise _google_error(exc) from None
    await HealthPoint.remove(session, user_id, data_type, current.remote_name)


async def preview(session, user_id: UUID, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Những gì sẽ được ghi lên Google (không gọi Google)."""
    point, derived = await build(session, user_id, kind, payload)
    return {"preview": True, "data_type": DATA_TYPE[kind], "data_point": point, "derived": derived}
