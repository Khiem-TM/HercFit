from datetime import datetime, timezone
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from schemas.common import EntityRead, InputSchema, JsonObject, Pagination, Percentage, PositiveMeasurement


class BodyMetricCreate(InputSchema):
    weight_kg: PositiveMeasurement
    height_cm: PositiveMeasurement | None = None
    body_fat_pct: Percentage | None = None
    muscle_mass_kg: PositiveMeasurement | None = None
    recorded_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    additional_metrics: JsonObject = Field(default_factory=dict)


# Corrections are complete new snapshots, not updates to stored measurements.
BodyMetricReplace = BodyMetricCreate


class BodyMetricRead(BodyMetricCreate, EntityRead):
    user_id: UUID


class BodyMetricQuery(Pagination):
    recorded_from: AwareDatetime | None = None
    recorded_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered_times(self):
        if self.recorded_from is not None and self.recorded_to is not None and self.recorded_from > self.recorded_to:
            raise ValueError("recorded_from must not be after recorded_to")
        return self
