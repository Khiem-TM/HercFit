"""Exercise definitions, typed performance snapshots and schedule prescriptions."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BeforeValidator, Field, computed_field, model_validator

from schemas.common import (
    EntityRead, ImageUrl, InputSchema, JsonObject, NonBlank, Pagination, PartialSchema, Version,
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


class MuscleGroup(StrEnum):
    """Primary muscle vocabulary; strength analytics group hard sets by it."""

    CHEST = "CHEST"
    BACK = "BACK"
    SHOULDERS = "SHOULDERS"
    BICEPS = "BICEPS"
    TRICEPS = "TRICEPS"
    FOREARMS = "FOREARMS"
    QUADS = "QUADS"
    HAMSTRINGS = "HAMSTRINGS"
    GLUTES = "GLUTES"
    CALVES = "CALVES"
    CORE = "CORE"
    FULL_BODY = "FULL_BODY"


# Unambiguous anatomical names map onto the coarse vocabulary; anything else is rejected.
MUSCLE_ALIASES = {
    "ABS": "CORE", "ABDOMINALS": "CORE", "OBLIQUES": "CORE", "TRANSVERSE_ABDOMINIS": "CORE", "RECTUS_ABDOMINIS": "CORE",
    "LATS": "BACK", "LATISSIMUS_DORSI": "BACK", "TRAPS": "BACK", "TRAPEZIUS": "BACK", "RHOMBOIDS": "BACK",
    "ERECTOR_SPINAE": "BACK", "LOWER_BACK": "BACK", "UPPER_BACK": "BACK",
    "DELTS": "SHOULDERS", "DELTOIDS": "SHOULDERS", "REAR_DELTS": "SHOULDERS", "FRONT_DELTS": "SHOULDERS",
    "PECS": "CHEST", "PECTORALS": "CHEST", "QUADRICEPS": "QUADS", "GLUTEUS_MAXIMUS": "GLUTES", "GLUTE": "GLUTES",
    "HAMSTRING": "HAMSTRINGS", "CALF": "CALVES", "BICEP": "BICEPS", "TRICEP": "TRICEPS", "FOREARM": "FOREARMS",
}


def muscle_name(value):
    if isinstance(value, str):
        key = value.strip().upper().replace(" ", "_").replace("-", "_")
        return MUSCLE_ALIASES.get(key, key)
    return value


Muscle = Annotated[MuscleGroup, BeforeValidator(muscle_name)]


class StrengthCategory(StrEnum):
    COMPOUND = "COMPOUND"
    ISOLATION = "ISOLATION"


class EquipmentType(StrEnum):
    BARBELL = "BARBELL"
    DUMBBELL = "DUMBBELL"
    MACHINE = "MACHINE"
    CABLE = "CABLE"
    BODYWEIGHT = "BODYWEIGHT"
    KETTLEBELL = "KETTLEBELL"
    BAND = "BAND"
    OTHER = "OTHER"


class EnduranceActivity(StrEnum):
    RUN = "RUN"
    WALK = "WALK"
    HIKE = "HIKE"
    CYCLE = "CYCLE"
    SWIM = "SWIM"
    ROW = "ROW"
    OTHER = "OTHER"


class EnduranceEnvironment(StrEnum):
    ROAD = "ROAD"
    TRACK = "TRACK"
    TRAIL = "TRAIL"
    TREADMILL = "TREADMILL"
    INDOOR = "INDOOR"
    OPEN_WATER = "OPEN_WATER"


class StrengthConfiguration(InputSchema):
    kind: Literal[ExerciseKind.STRENGTH] = ExerciseKind.STRENGTH
    category: StrengthCategory = StrengthCategory.COMPOUND
    equipment_type: EquipmentType = EquipmentType.OTHER
    movement_pattern: NonBlank | None = None
    secondary_muscles: list[Muscle] = Field(default_factory=list)
    unilateral: bool = False
    # e1RM is only meaningful for loadable multi-joint lifts; defaults follow category.
    e1rm_eligible: bool | None = None
    default_met: MET | None = None
    supported_load_modes: Annotated[list[LoadMode], Field(min_length=1)] = Field(
        default_factory=lambda: [LoadMode.EXTERNAL, LoadMode.BODYWEIGHT, LoadMode.ASSISTED],
    )

    @model_validator(mode="after")
    def default_e1rm(self) -> Self:
        if self.e1rm_eligible is None:
            self.e1rm_eligible = self.category == StrengthCategory.COMPOUND
        return self


class SportConfiguration(InputSchema):
    kind: Literal[ExerciseKind.SPORT] = ExerciseKind.SPORT
    sport: NonBlank
    default_met: MET | None = None
    met_source: NonBlank | None = None


class EnduranceConfiguration(InputSchema):
    kind: Literal[ExerciseKind.ENDURANCE] = ExerciseKind.ENDURANCE
    activity: EnduranceActivity
    environment: EnduranceEnvironment | None = None
    terrain: NonBlank | None = None
    default_met: MET | None = None
    met_source: NonBlank | None = None


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
    image_url: ImageUrl | None = None

    @model_validator(mode="after")
    def matching_configuration(self) -> Self:
        if self.configuration.kind != self.kind:
            raise ValueError("configuration.kind must match exercise kind")
        if self.kind == ExerciseKind.STRENGTH:
            self.muscle_groups = [MuscleGroup(muscle_name(group)) for group in self.muscle_groups]
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
    image_url: ImageUrl | None = None

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


class SetType(StrEnum):
    WARMUP = "WARMUP"
    WORKING = "WORKING"
    BACKOFF = "BACKOFF"
    DROP = "DROP"
    FAILURE = "FAILURE"


class Side(StrEnum):
    BOTH = "BOTH"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class StrengthSet(InputSchema):
    """Array order is set order. Zero external load represents an unloaded movement."""

    set_type: SetType = SetType.WORKING
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
    superset_group: Annotated[int, Field(strict=True, ge=1, le=50)] | None = None
    side: Side = Side.BOTH
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
    rpe: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)] | None = None
    distance_meters: Positive | None = None
    met: MET | None = None
    weight_kg: BodyWeight | None = None
    additional_data: JsonObject = Field(default_factory=dict)


class WorkoutType(StrEnum):
    EASY = "EASY"
    RECOVERY = "RECOVERY"
    LONG = "LONG"
    TEMPO = "TEMPO"
    THRESHOLD = "THRESHOLD"
    INTERVAL = "INTERVAL"
    FARTLEK = "FARTLEK"
    HILL = "HILL"
    PROGRESSION = "PROGRESSION"
    RACE = "RACE"
    WALK_RUN = "WALK_RUN"
    OTHER = "OTHER"


# Hard sessions for the 80/20 intensity-distribution check.
HARD_WORKOUTS = frozenset({
    WorkoutType.TEMPO, WorkoutType.THRESHOLD, WorkoutType.INTERVAL, WorkoutType.FARTLEK,
    WorkoutType.HILL, WorkoutType.PROGRESSION, WorkoutType.RACE,
})


class LapType(StrEnum):
    WARMUP = "WARMUP"
    WORK = "WORK"
    RECOVERY = "RECOVERY"
    COOLDOWN = "COOLDOWN"


class DataSource(StrEnum):
    MANUAL = "MANUAL"
    DEVICE = "DEVICE"
    GPX = "GPX"


HeartRate = Annotated[int, Field(strict=True, ge=25, le=250)]


class Lap(InputSchema):
    lap_type: LapType = LapType.WORK
    distance_meters: Positive
    duration_seconds: Positive
    avg_hr: HeartRate | None = None
    elevation_gain_meters: NonNegative | None = None


class EndurancePerformance(InputSchema):
    kind: Literal[ExerciseKind.ENDURANCE] = ExerciseKind.ENDURANCE
    workout_type: WorkoutType = WorkoutType.EASY
    duration_seconds: Positive
    moving_seconds: Positive | None = None
    distance_meters: Positive
    weight_kg: BodyWeight | None = None
    elevation_gain_meters: NonNegative | None = None
    elevation_loss_meters: NonNegative | None = None
    terrain: NonBlank | None = None
    avg_hr: HeartRate | None = None
    max_hr: HeartRate | None = None
    avg_cadence_spm: Annotated[int, Field(strict=True, ge=20, le=260)] | None = None
    rpe: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)] | None = None
    laps: list[Lap] = Field(default_factory=list)
    source: DataSource = DataSource.MANUAL

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.moving_seconds is not None and self.moving_seconds > self.duration_seconds:
            raise ValueError("moving_seconds cannot exceed duration_seconds")
        if self.avg_hr is not None and self.max_hr is not None and self.avg_hr > self.max_hr:
            raise ValueError("avg_hr cannot exceed max_hr")
        if self.laps and sum(lap.distance_meters for lap in self.laps) > self.distance_meters * 1.01:
            raise ValueError("Lap distances exceed the total distance")
        return self

    @property
    def pace_seconds_per_km(self) -> float:
        """Derived value; deliberately absent from writable and stored payloads."""
        return self.duration_seconds * 1000 / self.distance_meters


class EndurancePerformanceRead(EndurancePerformance):
    @model_validator(mode='before')
    @classmethod
    def accept_serialized_pace(cls, value):
        # Responses include computed fields; derive them again from validated
        # duration/distance when reading a response or idempotency replay.
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in _DERIVED_ENDURANCE}
        return value

    @computed_field
    @property
    def pace_seconds_per_km(self) -> float:
        return super().pace_seconds_per_km

    @computed_field
    @property
    def moving_pace_seconds_per_km(self) -> float | None:
        return self.moving_seconds * 1000 / self.distance_meters if self.moving_seconds else None

    @computed_field
    @property
    def speed_kmh(self) -> float:
        return self.distance_meters / 1000 / ((self.moving_seconds or self.duration_seconds) / 3600)

    @computed_field
    @property
    def lap_paces_seconds_per_km(self) -> list[float]:
        return [lap.duration_seconds * 1000 / lap.distance_meters for lap in self.laps]


_DERIVED_ENDURANCE = frozenset({
    "pace_seconds_per_km", "moving_pace_seconds_per_km", "speed_kmh", "lap_paces_seconds_per_km",
})


ExercisePerformance = Annotated[
    StrengthPerformance | SportPerformance | EndurancePerformance,
    Field(discriminator="kind"),
]
ExercisePerformanceRead = Annotated[
    StrengthPerformance | SportPerformance | EndurancePerformanceRead,
    Field(discriminator="kind"),
]


class CalorieEstimate(InputSchema):
    """An estimate with provenance; HERCFIT_ESTIMATE marks a server-side model result."""

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


# ---------------------------------------------------------------------------
# Prescriptions: what a schedule asks for. They express ranges and targets and
# are never confused with the performance that was actually achieved.
# ---------------------------------------------------------------------------

Reps = Annotated[int, Field(strict=True, ge=1, le=1000)]
RPE = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)]


class LoadTargetMode(StrEnum):
    KG = "KG"
    PCT_1RM = "PCT_1RM"
    RPE = "RPE"
    BODYWEIGHT = "BODYWEIGHT"


class LoadTarget(InputSchema):
    mode: LoadTargetMode
    value: NonNegative | None = None

    @model_validator(mode="after")
    def needs_value(self) -> Self:
        if self.mode != LoadTargetMode.BODYWEIGHT and self.value is None:
            raise ValueError(f"{self.mode} load target needs a value")
        if self.mode == LoadTargetMode.PCT_1RM and not 0 < (self.value or 0) <= 110:
            raise ValueError("PCT_1RM must be within (0, 110]")
        if self.mode == LoadTargetMode.RPE and (self.value or 0) > 10:
            raise ValueError("RPE load target must be <= 10")
        return self


class StrengthSetTarget(InputSchema):
    """One prescribed set group: `count` identical sets, e.g. 4 x 8-12 @ RPE 8."""

    count: Annotated[int, Field(strict=True, ge=1, le=20)] = 1
    set_type: SetType = SetType.WORKING
    reps_min: Reps | None = None
    reps_max: Reps | None = None
    hold_seconds: Positive | None = None
    load: LoadTarget | None = None
    rpe_target: RPE | None = None
    rir_target: Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)] | None = None
    rest_seconds: NonNegative | None = None
    tempo: NonBlank | None = None

    @model_validator(mode="after")
    def reps_or_hold(self) -> Self:
        if self.reps_min is None and self.hold_seconds is None:
            raise ValueError("A set target needs reps_min or hold_seconds")
        if self.reps_max is not None and (self.reps_min is None or self.reps_max < self.reps_min):
            raise ValueError("reps_max requires reps_min and must not be smaller")
        return self


class ProgressionRule(StrEnum):
    NONE = "NONE"
    LINEAR = "LINEAR"
    DOUBLE_PROGRESSION = "DOUBLE_PROGRESSION"


class Progression(InputSchema):
    rule: ProgressionRule = ProgressionRule.NONE
    increment_kg: Positive | None = None


class StrengthPrescription(InputSchema):
    kind: Literal[ExerciseKind.STRENGTH] = ExerciseKind.STRENGTH
    sets: Annotated[list[StrengthSetTarget], Field(min_length=1)]
    progression: Progression = Field(default_factory=Progression)


class StepType(StrEnum):
    WARMUP = "WARMUP"
    WORK = "WORK"
    RECOVERY = "RECOVERY"
    COOLDOWN = "COOLDOWN"


class TargetType(StrEnum):
    OPEN = "OPEN"
    PACE = "PACE"
    PACE_ZONE = "PACE_ZONE"
    HR_ZONE = "HR_ZONE"
    RPE = "RPE"


PACE_ZONES = ("E", "M", "T", "I", "R")
HR_ZONES = ("Z1", "Z2", "Z3", "Z4", "Z5")


class StepTarget(InputSchema):
    """PACE bounds are seconds per km; zones resolve against the athlete profile."""

    type: TargetType = TargetType.OPEN
    zone: NonBlank | None = None
    low: NonNegative | None = None
    high: NonNegative | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.type == TargetType.PACE_ZONE and self.zone not in PACE_ZONES:
            raise ValueError(f"PACE_ZONE zone must be one of {PACE_ZONES}")
        if self.type == TargetType.HR_ZONE and self.zone not in HR_ZONES:
            raise ValueError(f"HR_ZONE zone must be one of {HR_ZONES}")
        if self.type in {TargetType.PACE, TargetType.RPE} and self.low is None and self.high is None:
            raise ValueError(f"{self.type} target needs low and/or high")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError("Target low must not exceed high")
        return self


class Step(InputSchema):
    step_type: StepType = StepType.WORK
    duration_seconds: Positive | None = None
    distance_meters: Positive | None = None
    target: StepTarget = Field(default_factory=StepTarget)

    @model_validator(mode="after")
    def exactly_one_measure(self) -> Self:
        if (self.duration_seconds is None) == (self.distance_meters is None):
            raise ValueError("A step needs exactly one of duration_seconds or distance_meters")
        return self


class RepeatBlock(InputSchema):
    repeat: Annotated[int, Field(strict=True, ge=2, le=50)]
    steps: Annotated[list[Step], Field(min_length=1)]


class EndurancePrescription(InputSchema):
    kind: Literal[ExerciseKind.ENDURANCE] = ExerciseKind.ENDURANCE
    workout_type: WorkoutType = WorkoutType.EASY
    steps: Annotated[list[Step | RepeatBlock], Field(min_length=1)]

    def flat_steps(self) -> list[Step]:
        flat = []
        for step in self.steps:
            flat.extend(step.steps * step.repeat if isinstance(step, RepeatBlock) else [step])
        return flat


class EndurancePrescriptionRead(EndurancePrescription):
    @model_validator(mode="before")
    @classmethod
    def drop_derived(cls, value):
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in {"planned_distance_meters", "planned_duration_seconds"}}
        return value

    @computed_field
    @property
    def planned_distance_meters(self) -> float:
        """Sum of distance-defined steps; time-defined steps are not converted."""
        return sum(step.distance_meters or 0 for step in self.flat_steps())

    @computed_field
    @property
    def planned_duration_seconds(self) -> float:
        return sum(step.duration_seconds or 0 for step in self.flat_steps())


class SportPrescription(InputSchema):
    kind: Literal[ExerciseKind.SPORT] = ExerciseKind.SPORT
    duration_seconds: Positive
    intensity: ActivityIntensity = ActivityIntensity.MODERATE
    rpe_target: RPE | None = None


ExercisePrescription = Annotated[
    StrengthPrescription | SportPrescription | EndurancePrescription,
    Field(discriminator="kind"),
]
ExercisePrescriptionRead = Annotated[
    StrengthPrescription | SportPrescription | EndurancePrescriptionRead,
    Field(discriminator="kind"),
]


class ExercisePrescriptionInput(InputSchema):
    exercise_id: UUID
    prescription: ExercisePrescription
    note: str | None = None
