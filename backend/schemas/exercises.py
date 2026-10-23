"""Exercise definitions and typed performance snapshots; no calorie estimation."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, computed_field, model_validator

from schemas.common import (
    EntityRead, InputSchema, JsonObject, NonBlank, Pagination, PartialSchema, Version,
)
from schemas.enums import FoodSourceType

ExerciseCode = Annotated[NonBlank, Field(max_length=128)]
ExerciseName = Annotated[NonBlank, Field(max_length=512)]
NonNegative = Annotated[float, Field(ge=0, lt=1_000_000_000, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, lt=1_000_000_000, allow_inf_nan=False)]
BodyWeight = Annotated[float, Field(gt=0, lt=1000, allow_inf_nan=False)]
MET = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]
Calories = Annotated[
    Decimal, Field(ge=0, lt=1_000_000_000_000, max_digits=18, decimal_places=6, allow_inf_nan=False),
]


class ExerciseKind(StrEnum):
    STRENGTH = "STRENGTH"
    SPORT = "SPORT"
    ENDURANCE = "ENDURANCE"


class LoadMode(StrEnum):
    EXTERNAL = "EXTERNAL"
    BODYWEIGHT = "BODYWEIGHT"
    ASSISTED = "ASSISTED"


class ActivityIntensity(StrEnum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    VIGOROUS = "VIGOROUS"


class StrengthConfiguration(InputSchema):
    kind: Literal[ExerciseKind.STRENGTH] = ExerciseKind.STRENGTH
    movement_pattern: NonBlank | None = None
    unilateral: bool = False
    supported_load_modes: Annotated[list[LoadMode], Field(min_length=1)] = Field(
        default_factory=lambda: [LoadMode.EXTERNAL, LoadMode.BODYWEIGHT, LoadMode.ASSISTED],
    )


class SportConfiguration(InputSchema):
    kind: Literal[ExerciseKind.SPORT] = ExerciseKind.SPORT
    sport: NonBlank
    default_met: MET | None = None
    met_source: NonBlank | None = None


class EnduranceConfiguration(InputSchema):
    kind: Literal[ExerciseKind.ENDURANCE] = ExerciseKind.ENDURANCE
    activity: NonBlank
    terrain: NonBlank | None = None


ExerciseConfiguration = Annotated[
    StrengthConfiguration | SportConfiguration | EnduranceConfiguration,
    Field(discriminator="kind"),
]


class ExerciseCreate(InputSchema):
    name_vi: ExerciseName
    code: ExerciseCode | None = None
    name_en: ExerciseName | None = None
    kind: ExerciseKind
    instructions: str | None = None
    equipment: list[NonBlank] = Field(default_factory=list)
    muscle_groups: list[NonBlank] = Field(default_factory=list)
    configuration: ExerciseConfiguration

    @model_validator(mode="after")
    def matching_configuration(self) -> Self:
        if self.configuration.kind != self.kind:
            raise ValueError("configuration.kind must match exercise kind")
        return self


class SystemExerciseCreate(ExerciseCreate):
    code: ExerciseCode


class ExerciseUpdateRequest(PartialSchema):
    """PATCH cannot alter category, source or owner; configuration replaces as a whole."""

    non_nullable = frozenset({"code", "name_vi", "equipment", "muscle_groups", "configuration"})
    expected_version_id: Version
    code: ExerciseCode | None = None
    name_vi: ExerciseName | None = None
    name_en: ExerciseName | None = None
    instructions: str | None = None
    equipment: list[NonBlank] | None = None
    muscle_groups: list[NonBlank] | None = None
    configuration: ExerciseConfiguration | None = None

    def to_payload(self):
        return self.model_dump(mode="python", exclude_unset=True, exclude={"expected_version_id"})


class ExerciseRead(ExerciseCreate, EntityRead):
    code: ExerciseCode
    source_type: FoodSourceType
    owner_user_id: UUID | None


class ExerciseQuery(Pagination):
    search: str | None = None
    kind: ExerciseKind | None = None
    source_type: FoodSourceType | None = None


class StrengthSet(InputSchema):
    """Array order is set order. Zero external load represents an unloaded movement."""

    load_mode: LoadMode = LoadMode.EXTERNAL
    reps: Annotated[int, Field(strict=True, ge=1, le=100_000)] | None = None
    weight_kg: NonNegative | None = None
    bodyweight_kg: BodyWeight | None = None
    assistance_kg: NonNegative | None = None
    hold_seconds: Positive | None = None
    rest_seconds: NonNegative | None = None
    tempo: NonBlank | None = None
    rpe: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)] | None = None
    rir: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def complete_set(self) -> Self:
        if self.reps is None and self.hold_seconds is None:
            raise ValueError("A set needs reps or hold_seconds")
        if self.assistance_kg is not None and self.load_mode != LoadMode.ASSISTED:
            raise ValueError("assistance_kg requires ASSISTED load_mode")
        return self


class StrengthPerformance(InputSchema):
    kind: Literal[ExerciseKind.STRENGTH] = ExerciseKind.STRENGTH
    sets: Annotated[list[StrengthSet], Field(min_length=1)]
    duration_seconds: Positive | None = None


class SportPerformance(InputSchema):
    kind: Literal[ExerciseKind.SPORT] = ExerciseKind.SPORT
    duration_seconds: Positive
    intensity: ActivityIntensity
    met: MET | None = None
    weight_kg: BodyWeight | None = None
    additional_data: JsonObject = Field(default_factory=dict)


class EndurancePerformance(InputSchema):
    kind: Literal[ExerciseKind.ENDURANCE] = ExerciseKind.ENDURANCE
    duration_seconds: Positive
    distance_meters: Positive
    weight_kg: BodyWeight | None = None
    elevation_gain_meters: NonNegative | None = None
    elevation_loss_meters: NonNegative | None = None
    terrain: NonBlank | None = None

    @property
    def pace_seconds_per_km(self) -> float:
        """Derived value; deliberately absent from writable and stored payloads."""
        return self.duration_seconds * 1000 / self.distance_meters


class EndurancePerformanceRead(EndurancePerformance):
    @model_validator(mode='before')
    @classmethod
    def accept_serialized_pace(cls, value):
        # Responses include this computed field; derive it again from validated
        # duration/distance when reading a response or idempotency replay.
        if isinstance(value, dict):
            value = dict(value)
            value.pop('pace_seconds_per_km', None)
        return value

    @computed_field
    @property
    def pace_seconds_per_km(self) -> float:
        return super().pace_seconds_per_km


ExercisePerformance = Annotated[
    StrengthPerformance | SportPerformance | EndurancePerformance,
    Field(discriminator="kind"),
]
ExercisePerformanceRead = Annotated[
    StrengthPerformance | SportPerformance | EndurancePerformanceRead,
    Field(discriminator="kind"),
]


class CalorieEstimate(InputSchema):
    """A supplied estimate with provenance, never a locally calculated result."""

    kcal: Calories | None = None
    source: NonBlank | None = None
    method: NonBlank | None = None
    method_version: NonBlank | None = None
    inputs: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_calories_have_provenance(self) -> Self:
        if self.kcal is not None and (self.source is None or self.method is None):
            raise ValueError("Known kcal requires source and method")
        return self


class ExerciseActivityInput(InputSchema):
    exercise_id: UUID
    performance: ExercisePerformance
    calorie_estimate: CalorieEstimate = Field(default_factory=CalorieEstimate)
    note: str | None = None
