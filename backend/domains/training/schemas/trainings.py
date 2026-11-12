"""Nhật ký ăn uống/tập luyện thực tế; bên gọi không được truyền tổng hay cờ cũ.

Tách ra từ schemas.journals trong đợt tổ chức lại theo miền."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from domains.catalog.schemas.foods import Nutrient
from domains.shared.schemas.activity import ExerciseActivityInput, ExerciseActivityRead
from domains.shared.schemas.common import InputSchema, Name
from domains.shared.schemas.journal import JournalRead
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName, VersionedRequest

# Nhật ký tập của HercFit chỉ gồm buổi gym: bài STRENGTH và bài ghi nhanh "Tập gym (tổng quát)"
# (migration 0016). Buổi thể thao được ghi thẳng lên Google Health (Google là nguồn sự thật).
GYM_GENERAL_CODE = "gym_general"

DurationSeconds = Annotated[Decimal, Field(gt=0, lt=1000000000, max_digits=12, decimal_places=3, allow_inf_nan=False)]

class TrainingCreate(InputSchema):
    name: Name
    started_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: AwareDatetime | None = None
    duration_seconds: DurationSeconds | None = None
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    note: str | None = None
    source_entry_id: UUID | None = None
    # RPE buổi tập (CR-10) quyết định tải sRPE dùng chung cho mọi bộ môn.
    session_rpe: Annotated[Decimal, Field(ge=0, le=10, max_digits=4, decimal_places=2)] | None = None
    items: Annotated[list[ExerciseActivityInput], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_duration(self):
        if self.ended_at is not None and self.started_at is not None:
            duration = Decimal(str((self.ended_at - self.started_at).total_seconds())).quantize(Decimal("0.001"))
            if duration <= 0 or duration >= 1000000000:
                raise ValueError("ended_at must follow started_at within the supported duration")
            if self.duration_seconds is not None and self.duration_seconds != duration:
                raise ValueError("duration_seconds does not match the timestamps")
            self.duration_seconds = duration
        return self

class TrainingReplace(VersionedRequest, TrainingCreate):
    started_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def non_null_time(self):
        if "started_at" in self.model_fields_set and self.started_at is None:
            raise ValueError("started_at may be omitted but cannot be null")
        return self

class TrainingItemRead(ExerciseActivityRead):
    training_id: UUID
    kind: str | None
    duration_seconds: Decimal | None
    distance_meters: Decimal | None
    elevation_gain_meters: Decimal | None
    volume_kg: Decimal | None
    best_e1rm_kg: Decimal | None
    hard_sets: int | None
    working_sets: int | None

class TrainingRead(JournalRead):
    source_entry_id: UUID | None
    started_at: AwareDatetime
    ended_at: AwareDatetime | None
    duration_seconds: DurationSeconds | None
    energy_kcal: Nutrient | None
    calories_incomplete: bool
    discipline: Literal["STRENGTH", "ENDURANCE", "SPORT", "MIXED"]
    session_rpe: Decimal | None
    training_load: Decimal | None
    items: list[TrainingItemRead]
