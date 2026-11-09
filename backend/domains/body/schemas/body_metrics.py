from datetime import datetime, timezone
from uuid import UUID

from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from domains.shared.schemas.common import (
    BodyFatPercentage,
    EntityRead,
    HeightCm,
    InputSchema,
    JsonObject,
    MuscleMassKg,
    Pagination,
    Percentage,
    PositiveMeasurement,
    WeightKg,
)


# Vòng ngực / eo / hông (cm): khoảng hợp lý của người trưởng thành và trẻ lớn.
CircumferenceCm = Annotated[Decimal, Field(ge=30, le=250, max_digits=6, decimal_places=2, allow_inf_nan=False)]
CIRCUMFERENCES = ("chest_cm", "waist_cm", "hip_cm")
MEASUREMENTS = ("weight_kg", "height_cm", "body_fat_pct", "muscle_mass_kg", *CIRCUMFERENCES)


class BodyMetricBase(InputSchema):
    weight_kg: PositiveMeasurement
    height_cm: PositiveMeasurement | None = None
    body_fat_pct: Percentage | None = None
    muscle_mass_kg: PositiveMeasurement | None = None
    chest_cm: PositiveMeasurement | None = None
    waist_cm: PositiveMeasurement | None = None
    hip_cm: PositiveMeasurement | None = None
    recorded_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    additional_metrics: JsonObject = Field(default_factory=dict)


class BodyMetricCreate(BodyMetricBase):
    """One body measurement. Weight is optional: re-measuring the waist is not a new weigh-in."""
    weight_kg: WeightKg | None = None
    height_cm: HeightCm | None = None
    body_fat_pct: BodyFatPercentage | None = None
    muscle_mass_kg: MuscleMassKg | None = None
    chest_cm: CircumferenceCm | None = None
    waist_cm: CircumferenceCm | None = None
    hip_cm: CircumferenceCm | None = None

    @model_validator(mode="after")
    def any_measurement(self):
        if all(getattr(self, field) is None for field in MEASUREMENTS):
            raise ValueError("At least one measurement is required (weight, height, body fat, muscle mass or a circumference)")
        return self


# Lần sửa là snapshot mới đầy đủ, không phải cập nhật số đo đã lưu.
BodyMetricReplace = BodyMetricCreate


class BodyMetricRead(BodyMetricBase, EntityRead):
    user_id: UUID
    # Mẫu từ thiết bị (source GOOGLE_HEALTH) có thể chỉ chứa chiều cao hoặc mỡ cơ thể.
    weight_kg: PositiveMeasurement | None = None
    source: str = "MANUAL"


class BodyMetricQuery(Pagination):
    recorded_from: AwareDatetime | None = None
    recorded_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered_times(self):
        if self.recorded_from is not None and self.recorded_to is not None and self.recorded_from > self.recorded_to:
            raise ValueError("recorded_from must not be after recorded_to")
        return self
