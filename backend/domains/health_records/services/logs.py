"""Nhật ký sức khoẻ cá nhân: nước uống, dinh dưỡng, triệu chứng, tâm trạng, kỳ kinh, que thử rụng trứng.

* `source` là MANUAL khi người dùng ghi và AI_CONFIRMED khi trợ lý ghi sau khi
  người dùng xác nhận (principal quyết định, không phải client).
* Ảnh chụp có phiên bản: sửa cần `expected_version_id`; xoá là xoá mềm.
* Mọi lệnh ghi gọi hook xuất trong cùng transaction (M6): nếu người dùng
  đã bật xuất nhóm này lên Google, một dòng outbox được ghi nguyên tử.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core import principal as principals
from domains.nutrition.models.logs import HydrationLog, NutritionLog
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName
from domains.wellbeing.models.logs import (
    MEAL_TYPES, MOODS, OVULATION_RESULTS, SYMPTOMS, VALENCES, MenstrualPeriodLog, MoodLog, OvulationTestLog,
    SymptomLog,
)

Symptom = Literal[SYMPTOMS]  # type: ignore[valid-type]
Mood = Literal[MOODS]  # type: ignore[valid-type]
Valence = Literal[VALENCES]  # type: ignore[valid-type]
OvulationResult = Literal[OVULATION_RESULTS]  # type: ignore[valid-type]
MealType = Literal[MEAL_TYPES]  # type: ignore[valid-type]
Note = Annotated[str | None, Field(default=None, max_length=1000)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _LogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: Note = None


class HydrationLogCreate(_LogInput):
    consumed_at: AwareDatetime = Field(default_factory=_now)
    amount_ml: Annotated[Decimal, Field(gt=0, le=10000, max_digits=6, decimal_places=1)]


class NutritionLogCreate(_LogInput):
    consumed_at: AwareDatetime = Field(default_factory=_now)
    meal_type: MealType | None = None
    food_name: Annotated[str | None, Field(default=None, max_length=255)] = None
    energy_kcal: Annotated[Decimal | None, Field(default=None, ge=0, le=20000)] = None
    protein_g: Annotated[Decimal | None, Field(default=None, ge=0, le=2000)] = None
    carbohydrate_g: Annotated[Decimal | None, Field(default=None, ge=0, le=2000)] = None
    fat_g: Annotated[Decimal | None, Field(default=None, ge=0, le=2000)] = None
    meal_id: UUID | None = None
    food_id: UUID | None = None

    @model_validator(mode="after")
    def identifies_food(self):
        if self.food_name is None and self.meal_id is None and self.food_id is None:
            raise ValueError("food_name, meal_id or food_id is required")
        return self


class SymptomLogCreate(_LogInput):
    recorded_at: AwareDatetime = Field(default_factory=_now)
    symptoms: Annotated[list[Symptom], Field(min_length=1, max_length=20)]


class MoodLogCreate(_LogInput):
    recorded_at: AwareDatetime = Field(default_factory=_now)
    moods: Annotated[list[Mood], Field(default_factory=list, max_length=10)]
    valences: Annotated[list[Valence], Field(default_factory=list, max_length=3)]

    @model_validator(mode="after")
    def not_empty(self):
        if not self.moods and not self.valences:
            raise ValueError("moods or valences is required")
        return self


class MenstrualPeriodLogCreate(_LogInput):
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.ended_at is not None and self.ended_at <= self.started_at:
            raise ValueError("ended_at must follow started_at")
        return self


class OvulationTestLogCreate(_LogInput):
    recorded_at: AwareDatetime = Field(default_factory=_now)
    result: OvulationResult


KINDS: dict[str, dict[str, Any]] = {
    "hydration": {"model": HydrationLog, "schema": HydrationLogCreate, "time": "consumed_at", "export": "hydration",
                  "sensitive": False},
    "nutrition": {"model": NutritionLog, "schema": NutritionLogCreate, "time": "consumed_at", "export": "nutrition",
                  "sensitive": False},
    "symptoms": {"model": SymptomLog, "schema": SymptomLogCreate, "time": "recorded_at", "export": "symptoms",
                 "sensitive": True},
    "mood": {"model": MoodLog, "schema": MoodLogCreate, "time": "recorded_at", "export": "mood", "sensitive": True},
    "menstrual-period": {"model": MenstrualPeriodLog, "schema": MenstrualPeriodLogCreate, "time": "started_at",
                         "export": "reproductive", "sensitive": True},
    "ovulation-test": {"model": OvulationTestLog, "schema": OvulationTestLogCreate, "time": "recorded_at",
                       "export": "reproductive", "sensitive": True},
}
AGGREGATES = {"hydration": "HydrationLog", "nutrition": "NutritionLog", "symptoms": "SymptomLog", "mood": "MoodLog",
              "menstrual-period": "MenstrualPeriodLog", "ovulation-test": "OvulationTestLog"}


async def _emit(session, user_id: UUID, kind: str, entity: Any, op: str, **extra: Any) -> None:
    from domains.shared import write_hooks
    await write_hooks.emit(session, user_id, AGGREGATES[kind], entity, op, **extra)


def spec(kind: str) -> dict[str, Any]:
    if kind not in KINDS:
        raise HTTPException(404, "Unknown log kind")
    return KINDS[kind]


def _values(kind: str, payload: BaseModel) -> dict[str, Any]:
    info = spec(kind)
    data = payload.model_dump(mode="python")
    moment = data[info["time"]]
    data["local_date"] = moment.astimezone(ZoneInfo(data["timezone"])).date()
    data["utc_offset_s"] = int(moment.astimezone(ZoneInfo(data["timezone"])).utcoffset().total_seconds())
    return data


async def _read_access(session, user_id: UUID, kind: str) -> None:
    """Trợ lý chỉ đọc nhật ký nhạy cảm khi có consent `sensitive` riêng."""
    if KINDS[kind]["sensitive"] and principals.is_agent():
        from domains.identity import consent

        await consent.require_device_access(session, user_id, "sensitive")


def _transient(kind: str, user_id: UUID, payload: dict[str, Any]) -> Any:
    info = spec(kind)
    data = _values(kind, info["schema"].model_validate(payload))
    return info["model"](user_id=user_id, source="AI_CONFIRMED" if principals.is_agent() else "MANUAL", **data)


async def preview(session, user_id: UUID, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Những gì một lệnh tạo sẽ lưu cục bộ và gửi lên Google; không ghi gì."""
    from domains.shared import write_hooks

    entity = _transient(kind, user_id, {k: v for k, v in payload.items() if k != "preview_sha256"})
    effects = await write_hooks.preview(session, user_id, AGGREGATES[kind], entity)
    local = {c.name: getattr(entity, c.name) for c in entity.__table__.columns
             if c.name not in ("id", "user_id", "created_at", "updated_at", "version_id", "is_active")}
    return {"local": local, "google": effects, "preview_sha256": write_hooks.effects_sha256([local, effects])}


async def create(session, user_id: UUID, kind: str, payload: dict[str, Any]) -> Any:
    expected = payload.get("preview_sha256")
    if expected is not None:
        # Thẻ đã xác nhận gắn đúng với những gì nó hiển thị (dòng cục bộ và tác động lên Google).
        current = await preview(session, user_id, kind, payload)
        if current["preview_sha256"] != expected:
            from fastapi.encoders import jsonable_encoder

            raise HTTPException(409, {"code": "preview_stale", "message": "Dữ liệu xem trước đã thay đổi; hãy xem lại.",
                                      "preview": jsonable_encoder(current)})
    entity = _transient(kind, user_id, {k: v for k, v in payload.items() if k != "preview_sha256"})
    session.add(entity)
    await session.flush()
    await _emit(session, user_id, kind, entity, "CREATE")
    return entity


async def get(session, user_id: UUID, kind: str, log_id: UUID) -> Any:
    await _read_access(session, user_id, kind)
    model = spec(kind)["model"]
    entity = (await session.execute(select(model).where(model.id == log_id, model.user_id == user_id,
                                                        model.is_active.is_(True)))).scalar_one_or_none()
    if entity is None:
        raise HTTPException(404, "Log not found")
    return entity


async def list_logs(session, user_id: UUID, kind: str, *, start: date | None, end: date | None, limit: int,
                    cursor: tuple[datetime, UUID] | None) -> list[Any]:
    await _read_access(session, user_id, kind)
    info = spec(kind)
    model, column = info["model"], getattr(info["model"], info["time"])
    query = select(model).where(model.user_id == user_id, model.is_active.is_(True))
    if start is not None:
        query = query.where(model.local_date >= start)
    if end is not None:
        query = query.where(model.local_date <= end)
    if cursor is not None:
        from sqlalchemy import tuple_
        query = query.where(tuple_(column, model.id) < cursor)
    return list((await session.execute(query.order_by(column.desc(), model.id.desc()).limit(limit))).scalars())


async def replace(session, user_id: UUID, kind: str, log_id: UUID, payload: dict[str, Any],
                  expected_version_id: int) -> Any:
    entity = await get(session, user_id, kind, log_id)
    if entity.version_id != expected_version_id:
        raise HTTPException(409, "Version has changed; reload before editing")
    if entity.source == "GOOGLE_HEALTH":
        raise HTTPException(409, "Imported entries are edited in their source app")
    data = _values(kind, spec(kind)["schema"].model_validate(payload))
    for key, value in data.items():
        setattr(entity, key, value)
    await session.flush()
    entity.version_id  # noqa: B018  (phiên bản sau flush là phiên bản aggregate được xuất)
    await _emit(session, user_id, kind, entity, "UPDATE")
    return entity


async def delete(session, user_id: UUID, kind: str, log_id: UUID, expected_version_id: int, *,
                 remote: bool = False) -> None:
    """Xoá mềm. Bản trên Google chỉ bị xoá khi người dùng yêu cầu tường minh (`remote`)."""
    entity = await get(session, user_id, kind, log_id)
    if entity.version_id != expected_version_id:
        raise HTTPException(409, "Version has changed; reload before editing")
    entity.is_active = False
    await session.flush()
    await _emit(session, user_id, kind, entity, "DELETE", remote=remote)
