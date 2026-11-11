"""Dữ liệu sức khoẻ từ thiết bị đeo (Google Health API) và hồ sơ sức khoẻ hợp nhất.

Tách ra từ schemas.health trong đợt tổ chức lại theo miền."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from domains.shared.schemas.common import EntityRead, InputSchema
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE, DateRangeQuery, TimeZoneName


HEALTH_PROVIDER = "GOOGLE_HEALTH"

MEASUREMENT_SOURCES = ("MANUAL", HEALTH_PROVIDER)

MeasurementSource = Literal["MANUAL", "GOOGLE_HEALTH"]

ConnectionStatus = Literal["ACTIVE", "NEEDS_REAUTH", "REVOKED", "ERROR"]

SampleType = Literal["BLOOD_GLUCOSE", "CORE_BODY_TEMPERATURE"]

ValueSource = Literal["DECLARED", "MEASURED", "PROVIDER", "DERIVED"]

# ---------------------------------------------------------------------------
# Phân loại dùng chung (thuần; agentic.knowledge_graph.model cũng import)
# ---------------------------------------------------------------------------
# Ngưỡng BMI châu Á - Thái Bình Dương của WHO, phù hợp với người trưởng thành Việt Nam.
BMI_ASIA = ((18.5, "underweight"), (23.0, "normal"), (25.0, "overweight"), (float("inf"), "obese"))

BMI_LABELS = {"underweight": "thiếu cân", "normal": "bình thường", "overweight": "thừa cân", "obese": "béo phì"}

# Các dải bước chân của Tudor-Locke ánh xạ vào các mức vận động mà mục tiêu năng lượng dùng.
STEP_LEVELS = ((5000, "sedentary"), (7500, "light"), (10000, "moderate"), (12500, "active"), (float("inf"), "very_active"))

ACTIVITY_LABELS = {"sedentary": "ít vận động", "light": "vận động nhẹ", "moderate": "vận động vừa",
                   "active": "năng động", "very_active": "rất năng động"}

ACTIVITY_ORDER = tuple(level for _, level in STEP_LEVELS)

WHO_ACTIVE_MINUTES_PER_WEEK = 150

# Số phút tập mỗi tuần (buổi đã ghi hoặc buổi vận động của thiết bị) so với cùng các mức,
# neo theo các dải 150/300 phút của WHO. Điện thoại để ở nhà khi chạy ghi được ít
# bước, nên buổi tập là cận dưới mà số bước không thấy được.
EXERCISE_LEVELS = ((60, "sedentary"), (150, "light"), (300, "moderate"), (450, "active"), (float("inf"), "very_active"))

# Nhịp tim nghỉ cao hơn đường nền 28 ngày chừng này, hoặc HRV thấp hơn
# chừng này, là tín hiệu phục hồi đáng nhắc tới (không bao giờ là chẩn đoán).
RHR_ELEVATION_BPM = 5

HRV_DROP_PCT = 15

# Một ngày được tính là có đeo khi thiết bị ghi được ít nhất chừng này bước.
WORN_DAY_MIN_STEPS = 500

def classify_bmi(bmi: float | None) -> str | None:
    if bmi is None:
        return None
    return next(label for limit, label in BMI_ASIA if bmi < limit)

def activity_level_from_steps(steps_per_day: float | None) -> str | None:
    if steps_per_day is None:
        return None
    return next(level for limit, level in STEP_LEVELS if steps_per_day < limit)

def activity_level_from_exercise(minutes_per_week: float | None) -> str | None:
    if minutes_per_week is None:
        return None
    return next(level for limit, level in EXERCISE_LEVELS if minutes_per_week < limit)

def recommended_sleep_hours(age: int | None) -> tuple[float, float]:
    """Khoảng khuyến nghị của National Sleep Foundation; mặc định cho người trưởng thành."""
    if age is not None and age < 14:
        return 9.0, 11.0
    if age is not None and age < 18:
        return 8.0, 10.0
    if age is not None and age >= 65:
        return 7.0, 8.0
    return 7.0, 9.0

# ---------------------------------------------------------------------------
# Chuỗi thời gian đo được
# ---------------------------------------------------------------------------
class DailyHealthRead(EntityRead):
    local_date: date
    source: str
    timezone: str
    steps: int | None
    distance_m: Decimal | None
    floors: int | None
    active_minutes: int | None
    active_minutes_by_level: dict[str, Any]
    active_zone_minutes: int | None
    total_kcal: Decimal | None
    active_kcal: Decimal | None
    resting_hr_bpm: int | None
    hr_avg_bpm: Decimal | None
    hr_min_bpm: int | None
    hr_max_bpm: int | None
    hrv_ms: Decimal | None
    spo2_avg_pct: Decimal | None
    respiratory_rate: Decimal | None
    vo2_max: Decimal | None
    hydration_ml: Decimal | None
    sleep_minutes: int | None
    skin_temp_delta_c: Decimal | None
    sedentary_minutes: int | None = None

class SleepSessionRead(EntityRead):
    source: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    local_date: date
    sleep_type: str | None
    is_main: bool
    is_nap: bool
    minutes_asleep: int | None
    minutes_awake: int | None
    minutes_in_period: int | None
    minutes_to_fall_asleep: int | None
    deep_minutes: int | None
    light_minutes: int | None
    rem_minutes: int | None
    awake_minutes: int | None
    efficiency_pct: Decimal | None
    data_source: dict[str, Any]

class DeviceWorkoutRead(EntityRead):
    source: str
    started_at: AwareDatetime
    ended_at: AwareDatetime
    local_date: date
    exercise_type: str | None
    display_name: str | None
    active_seconds: int | None
    energy_kcal: Decimal | None
    distance_m: Decimal | None
    steps: int | None
    avg_hr_bpm: int | None
    active_zone_minutes: int | None
    hr_zone_seconds: dict[str, Any]
    elevation_gain_m: Decimal | None
    avg_speed_mps: Decimal | None
    run_vo2_max: Decimal | None
    data_source: dict[str, Any]

class HealthSampleRead(EntityRead):
    source: str
    sample_type: str
    measured_at: AwareDatetime
    value: Decimal
    unit: str
    details: dict[str, Any]

class HeartRateHourRead(BaseModel):
    """Nhịp tim trong một giờ (rollUp của Google): giờ không có mẫu thì không có dòng."""
    start_at: AwareDatetime
    end_at: AwareDatetime
    hour: int = Field(ge=0, le=23, description="Giờ địa phương bắt đầu cửa sổ")
    bpm_avg: Decimal
    bpm_min: int | None
    bpm_max: int | None


class HealthSampleQuery(DateRangeQuery):
    sample_type: SampleType | None = None

class HealthOverviewQuery(InputSchema):
    days: Annotated[int, Field(strict=True, ge=7, le=90)] = 28
    timezone: TimeZoneName = DEFAULT_TIMEZONE
    end_date: date | None = None

    @model_validator(mode="after")
    def valid_end(self):
        if self.end_date == date.max:
            raise ValueError("Date is out of range")
        return self

# ---------------------------------------------------------------------------
# Hồ sơ và tổng quan suy ra (tính lúc đọc, không bao giờ lưu)
# ---------------------------------------------------------------------------
class ProfileValue(BaseModel):
    value: float | int | str | None
    source: ValueSource
    observed_at: date | datetime | None = None
    label: str | None = None

class HealthProfileRead(BaseModel):
    as_of: date
    timezone: str
    connected: bool
    age: ProfileValue | None = None
    sex: ProfileValue | None = None
    height_cm: ProfileValue | None = None
    weight_kg: ProfileValue | None = None
    body_fat_pct: ProfileValue | None = None
    bmi: ProfileValue | None = None
    resting_hr_bpm: ProfileValue | None = None
    max_hr_bpm: ProfileValue | None = None
    hrv_ms: ProfileValue | None = None
    vo2_max: ProfileValue | None = None
    activity_level: ProfileValue | None = None
    observed_activity_level: ProfileValue | None = None
    steps_avg_7d: float | None = None
    steps_avg_28d: float | None = None
    active_minutes_7d: int | None = None
    sleep_avg_minutes_7d: float | None = None
    worn_days_28d: int = 0
    missing_fields: list[str] = []
    conflicts: list[str] = []

class ActivityOverview(BaseModel):
    days_with_data: int
    steps_avg: float | None
    steps_avg_7d: float | None
    steps_trend_pct: float | None
    distance_km_avg: float | None
    active_minutes_week: float | None
    meets_who_guideline: bool | None
    active_zone_minutes_week: float | None
    total_kcal_avg: float | None
    active_kcal_avg: float | None
    observed_level: str | None
    workouts: int
    workout_minutes: float
    workout_types: dict[str, int]

class SleepOverview(BaseModel):
    nights: int
    avg_minutes: float | None
    avg_minutes_7d: float | None
    recommended_hours: tuple[float, float]
    nights_below_recommended: int
    deep_pct: float | None
    rem_pct: float | None
    efficiency_pct: float | None
    bedtime_stdev_minutes: float | None
    last_night: SleepSessionRead | None

class RecoveryOverview(BaseModel):
    resting_hr_7d: float | None
    resting_hr_baseline: float | None
    resting_hr_elevated: bool | None
    hrv_7d: float | None
    hrv_baseline: float | None
    hrv_suppressed: bool | None
    spo2_avg: float | None
    respiratory_rate_avg: float | None
    signals: list[str]

class EnergyOverview(BaseModel):
    complete_days: int
    intake_kcal_avg: float | None
    device_expenditure_kcal_avg: float | None
    balance_kcal_avg: float | None
    weight_change_kg: float | None
    note: str | None

class HealthOverviewRead(BaseModel):
    start_date: date
    end_date: date
    timezone: str
    connected: bool
    activity: ActivityOverview
    sleep: SleepOverview
    recovery: RecoveryOverview
    energy: EnergyOverview
    notes: list[str]
