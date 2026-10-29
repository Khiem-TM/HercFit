"""Athlete profile and read models for training analytics, insights and templates."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from schemas.common import InputSchema, NonBlank, ReadSchema
from schemas.tracking import DEFAULT_TIMEZONE, TimeZoneName

Discipline = Literal["STRENGTH", "ENDURANCE", "SPORT", "MIXED"]
PaceSeconds = Annotated[float, Field(ge=120, le=1200, allow_inf_nan=False)]


class RecentRace(InputSchema):
    distance_meters: Annotated[float, Field(gt=0, le=200_000, allow_inf_nan=False)]
    time_seconds: Annotated[float, Field(gt=0, le=200_000, allow_inf_nan=False)]
    race_date: date | None = None


class TrainingProfile(InputSchema):
    """Stored in users.personal_info['training']; no dedicated table."""

    experience_level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"] = "BEGINNER"
    primary_focus: Literal["STRENGTH", "RUNNING", "HYBRID"] = "HYBRID"
    available_days: Annotated[int, Field(strict=True, ge=1, le=7)] = 3
    session_minutes: Annotated[int, Field(strict=True, ge=15, le=300)] = 60
    max_hr: Annotated[int, Field(strict=True, ge=100, le=230)] | None = None
    resting_hr: Annotated[int, Field(strict=True, ge=25, le=120)] | None = None
    threshold_pace_s_per_km: PaceSeconds | None = None
    recent_race: RecentRace | None = None
    # Reference one-rep maxes by catalog exercise code, used for %1RM targets.
    one_rep_max: dict[NonBlank, Annotated[float, Field(gt=0, le=1000)]] = Field(default_factory=dict)
    injuries: list[NonBlank] = Field(default_factory=list)
    equipment: list[NonBlank] = Field(default_factory=list)

    @model_validator(mode="after")
    def heart_rates(self):
        if self.max_hr and self.resting_hr and self.resting_hr >= self.max_hr:
            raise ValueError("resting_hr must be below max_hr")
        return self


class TrainingProfileRead(ReadSchema):
    profile: TrainingProfile
    configured: bool
    hr_zones: dict[str, list[int]] | None
    pace_zones: dict[str, list[int]] | None
    threshold_source: Literal["PROFILE", "RECENT_RACE"] | None
    race_predictions_seconds: dict[str, int] | None


class AnalyticsQuery(InputSchema):
    start_date: date
    end_date: date
    timezone: TimeZoneName = DEFAULT_TIMEZONE

    @model_validator(mode="after")
    def bounded(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 366:
            raise ValueError("Use an ordered range of at most 366 days")
        return self


class InsightQuery(InputSchema):
    end_date: date | None = None
    timezone: TimeZoneName = DEFAULT_TIMEZONE


class StrengthProgressQuery(AnalyticsQuery):
    exercise_id: UUID


class WeekSummary(ReadSchema):
    week_start: date
    sessions: int
    sessions_by_discipline: dict[str, int]
    training_load: Decimal | None
    duration_seconds: Decimal
    energy_kcal: Decimal | None
    run_distance_meters: Decimal
    run_duration_seconds: Decimal
    run_pace_seconds_per_km: float | None
    strength_volume_kg: Decimal
    hard_sets_by_muscle: dict[str, int]
    planned_sessions: int
    completed_planned_sessions: int
    adherence_pct: float | None


class TrainingSummaryRead(ReadSchema):
    timezone: str
    start_date: date
    end_date: date
    weeks: list[WeekSummary]


class DailyLoad(ReadSchema):
    date: date
    load: Decimal
    acute_7d: Decimal
    chronic_28d_weekly: Decimal
    acwr: float | None


class TrainingLoadRead(ReadSchema):
    timezone: str
    start_date: date
    end_date: date
    days: list[DailyLoad]
    monotony_7d: float | None
    strain_7d: float | None
    sessions_without_rpe: int


class StrengthSession(ReadSchema):
    date: date
    training_id: UUID
    best_e1rm_kg: Decimal | None
    volume_kg: Decimal | None
    hard_sets: int | None
    top_set: dict | None


class StrengthProgressRead(ReadSchema):
    exercise_id: UUID
    exercise_name: str
    sessions: list[StrengthSession]
    best_e1rm_kg: Decimal | None
    e1rm_change_pct_4w: float | None


class PersonalRecord(ReadSchema):
    exercise_id: UUID | None
    exercise_name: str
    best_e1rm_kg: Decimal | None
    best_e1rm_date: date | None
    rep_maxes_kg: dict[str, dict]


class StrengthRecordsRead(ReadSchema):
    records: list[PersonalRecord]


class RunningWeek(ReadSchema):
    week_start: date
    runs: int
    distance_meters: Decimal
    duration_seconds: Decimal
    longest_run_meters: Decimal
    pace_seconds_per_km: float | None


class RunningSummaryRead(ReadSchema):
    timezone: str
    start_date: date
    end_date: date
    weeks: list[RunningWeek]
    pace_by_workout_type: dict[str, float]
    easy_share_pct: float | None
    best_efforts_seconds: dict[str, dict]
    race_predictions_seconds: dict[str, int] | None


class Insight(ReadSchema):
    code: str
    severity: Literal["INFO", "NOTICE", "WARNING", "POSITIVE"]
    discipline: Literal["STRENGTH", "RUNNING", "GENERAL", "NUTRITION"]
    message_vi: str
    evidence: dict


class InsightsRead(ReadSchema):
    end_date: date
    timezone: str
    insights: list[Insight]


class TemplateSummary(ReadSchema):
    code: str
    kind: Literal["PROGRAM", "WORKOUT"]
    discipline: Literal["STRENGTH", "RUNNING", "HYBRID"]
    name_vi: str
    description_vi: str
    level: Literal["BEGINNER", "INTERMEDIATE", "ADVANCED"]
    weeks: int | None
    sessions_per_week: int | None


class TemplateScheduleQuery(InputSchema):
    start_date: date
    weeks: Annotated[int, Field(strict=True, ge=1, le=16)] | None = None
    name: NonBlank | None = None
