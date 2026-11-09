"""Các tool API trong danh sách cho phép. Kiểu đầu vào và đầu ra là hợp đồng thật của backend."""

from datetime import date as _date
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, create_model

from agentic.research.contracts import ExerciseFinalization, ResolveQuery
from agentic.tools.definitions.base import ToolSpec
from agentic.tools.schemas.common import (
    Empty,
    InputSchema,
    PersonalInfo,
    Resource,
    TemplatePreview,
    TimezoneQuery,
    VersionedResource,
)
from domains.analytics.schemas.daily_health import DailyAssessmentRead
from domains.analytics.schemas.progress import ProgressRead
from domains.body.schemas.body_metrics import BodyMetricCreate, BodyMetricQuery, BodyMetricRead
from domains.catalog.schemas.exercises import ExerciseCreate, ExerciseQuery, ExerciseRead
from domains.catalog.schemas.foods import FoodCreate, FoodQuery, FoodRead
from domains.goals_plans.schemas.goal import GoalCreate, GoalRead, GoalUpdateRequest
from domains.goals_plans.schemas.plans import (
    PlanEnd,
    TrainingPlanCreate,
    TrainingPlanEntryRead,
    TrainingPlanRead,
    TrainingPlanReplace,
)
from domains.health_records.schemas.health import (
    DailyHealthRead,
    DeviceWorkoutRead,
    HealthOverviewQuery,
    HealthOverviewRead,
    HealthProfileRead,
    HealthSampleQuery,
    HealthSampleRead,
    SleepSessionRead,
)
from domains.identity.schemas.user import OnboardingInput, UserRead, UserUpdate
from domains.nutrition.schemas.meals import MealCreate, MealRead, MealReplace
from domains.nutrition.schemas.nutrition import NutritionTargetsRead
from domains.shared.schemas.common import Pagination
from domains.shared.schemas.tracking import DateRangeQuery, JournalQuery, ScheduleEntryQuery
from domains.training.schemas.training import (
    AnalyticsQuery,
    InsightQuery,
    InsightsRead,
    RunningSummaryRead,
    StrengthProgressQuery,
    StrengthProgressRead,
    StrengthRecordsRead,
    TemplateSummary,
    TrainingLoadRead,
    TrainingProfile,
    TrainingProfileRead,
    TrainingSummaryRead,
)
from domains.training.schemas.trainings import TrainingCreate, TrainingRead, TrainingReplace
from integrations.google_health.records import HydrationInput, SleepInput, SportInput
from integrations.google_health.schemas import HealthConnectionRead, HealthRecordRead

REGISTRY: dict[str, ToolSpec] = {}


def add(name, domain, method, path, schema, output, description, body=False):
    REGISTRY[name] = ToolSpec(
        name, domain, method, "/api" + path, schema, output, description, body
    )


def with_id(schema):
    return create_model(schema.__name__ + "WithID", __base__=schema, resource_id=(UUID, ...))


add("get_profile", "profile", "GET", "/profile", Empty, UserRead, "Read authenticated profile.")
add(
    "update_profile",
    "profile",
    "PATCH",
    "/profile",
    UserUpdate,
    UserRead,
    "Update only supplied profile fields.",
    True,
)
# Phần gộp đối tượng gốc được client gỡ bọc; trường danh tính không bao giờ được chấp nhận.
add(
    "merge_personal_info",
    "profile",
    "PATCH",
    "/profile/personal-info",
    PersonalInfo,
    UserRead,
    "Merge top-level personal_info groups; nested groups replace as a whole.",
    True,
)
add(
    "onboard",
    "profile",
    "POST",
    "/profile/onboarding",
    OnboardingInput,
    UserRead,
    "Save confirmed onboarding profile, optional metric and goal atomically.",
    True,
)
for domain, path, create, read, query, replace in [
    (
        "metrics",
        "body-metrics",
        BodyMetricCreate,
        BodyMetricRead,
        BodyMetricQuery,
        BodyMetricCreate,
    ),
    ("goals", "goals", GoalCreate, GoalRead, Pagination, GoalUpdateRequest),
    ("meals", "meals", MealCreate, MealRead, JournalQuery, MealReplace),
    ("trainings", "trainings", TrainingCreate, TrainingRead, JournalQuery, TrainingReplace),
    ("foods", "foods", FoodCreate, FoodRead, FoodQuery, None),
    ("exercises", "exercises", ExerciseCreate, ExerciseRead, ExerciseQuery, None),
]:
    add(
        "list_" + domain,
        domain,
        "GET",
        "/" + path,
        query,
        list[read],
        "Search/list " + domain + " with filters and pagination. Empty list means no match.",
    )
    add(
        "get_" + domain,
        domain,
        "GET",
        "/" + path + "/{resource_id}",
        Resource,
        read,
        "Read a specific " + domain + " record.",
    )
    add(
        "create_" + domain,
        domain,
        "POST",
        "/" + path + ("/confirm" if domain == "goals" else ""),
        create,
        read,
        "Propose creation of " + domain + ". Must await human confirmation.",
        True,
    )
    if replace:
        add(
            "update_" + domain,
            domain,
            "PATCH" if domain == "goals" else "PUT",
            "/" + path + "/{resource_id}",
            with_id(replace),
            read,
            "Replace snapshot (returns NEW ID) or patch goal. Read existing record first; preserve omitted snapshot values explicitly.",
            True,
        )
        add(
            "delete_" + domain,
            domain,
            "DELETE",
            "/" + path + "/{resource_id}",
            VersionedResource if domain in {"meals", "trainings"} else Resource,
            None,
            "Soft delete the specified record after confirmation.",
        )
add(
    "latest_metrics",
    "metrics",
    "GET",
    "/body-metrics/latest",
    Empty,
    BodyMetricRead,
    "Read latest measurement; 404 means no measurements.",
)
add(
    "current_goal",
    "goals",
    "GET",
    "/goals/current",
    Empty,
    GoalRead,
    "Read active goal; 404 means no active goal.",
)
for action in ["complete", "cancel"]:
    add(
        action + "_goal",
        "goals",
        "POST",
        "/goals/{resource_id}/" + action,
        Resource,
        GoalRead,
        action + " the active goal after confirmation.",
    )
add(
    "get_progress",
    "progress",
    "GET",
    "/progress",
    DateRangeQuery,
    ProgressRead,
    "Read daily progress for explicit start_date/end_date and timezone.",
)

# Finalize tra cứu dùng cùng adapter xem trước/băm/phê duyệt như các lệnh ghi khác. Chỉ bài tập được tra cứu web;
# món ăn chưa có trong catalog thì hỏi bằng thẻ món thiếu (services/food_gap.py).
for domain, schema in [("exercises", ExerciseFinalization)]:
    add(
        "resolve_" + domain,
        domain,
        "GET",
        "/" + domain + "/resolve",
        ResolveQuery,
        dict,
        "Resolve exact catalog identities, aliases and possible variants before research.",
    )
    add(
        "finalize_" + domain,
        domain,
        "POST",
        "/" + domain + "/research-finalizations",
        schema,
        dict,
        "Save the immutable verified research command after human confirmation.",
        True,
    )

# Kế hoạch tập (chỉ định) và phân tích huấn luyện tất định.


add(
    "current_training_plan",
    "training_plans",
    "GET",
    "/training-plans/current",
    Empty,
    TrainingPlanRead,
    "Read the active training schedule with its sessions; completed_at marks sessions the user ticked as done. 404 means none.",
)
add(
    "get_training_plans",
    "training_plans",
    "GET",
    "/training-plans/{resource_id}",
    Resource,
    TrainingPlanRead,
    "Read one training schedule.",
)
add(
    "list_training_plan_entries",
    "training_plans",
    "GET",
    "/training-plans/{resource_id}/entries",
    with_id(ScheduleEntryQuery),
    list[TrainingPlanEntryRead],
    "List scheduled sessions (optionally on_date or start/end date) of a training schedule.",
)
add(
    "list_training_templates",
    "training_plans",
    "GET",
    "/training/templates",
    Empty,
    list[TemplateSummary],
    "List program templates (Gym/Running/Hybrid) and single running workouts.",
)
add(
    "preview_training_template",
    "training_plans",
    "GET",
    "/training/templates/{resource_id}/schedule",
    TemplatePreview,
    TrainingPlanCreate,
    "Build a schedule preview from a program template. Read-only; pass the returned payload unchanged to create_training_plans.",
)
add(
    "create_training_plans",
    "training_plans",
    "POST",
    "/training-plans",
    TrainingPlanCreate,
    TrainingPlanRead,
    "Propose the training schedule when current_training_plan is 404; the backend attaches it to the plan of the current goal. "
    "Items use prescription (targets), not performance. Must await confirmation.",
    True,
)
add(
    "update_training_plans",
    "training_plans",
    "PUT",
    "/training-plans/{resource_id}",
    with_id(TrainingPlanReplace),
    TrainingPlanRead,
    "Replace a training schedule as a complete new version. Read it first. Must await confirmation.",
    True,
)
add(
    "end_training_plan",
    "training_plans",
    "POST",
    "/training-plans/{resource_id}/end",
    with_id(PlanEnd),
    TrainingPlanRead,
    "End a training schedule after confirmation.",
    True,
)

add(
    "get_nutrition_targets",
    "progress",
    "GET",
    "/nutrition/targets",
    TimezoneQuery,
    NutritionTargetsRead,
    "Daily energy and macro targets computed by the backend (Mifflin-St Jeor BMR, TDEE, goal adjustment with safety "
    "floors), kcal eaten and remaining today, smoothed weight trend and adaptive expenditure. Never compute these yourself.",
)
add(
    "get_training_profile",
    "coaching",
    "GET",
    "/training/profile",
    Empty,
    TrainingProfileRead,
    "Athlete profile with HR zones, pace zones and race predictions.",
)
add(
    "update_training_profile",
    "coaching",
    "PUT",
    "/training/profile",
    TrainingProfile,
    TrainingProfileRead,
    "Replace the athlete profile (level, focus, HR, threshold pace, recent race, 1RMs). Must await confirmation.",
    True,
)
add(
    "get_training_insights",
    "coaching",
    "GET",
    "/training/insights",
    InsightQuery,
    InsightsRead,
    "Deterministic findings (overload/ACWR, mileage jump, no rest, intensity mix, muscle volume, plateau, PR, adherence, fueling) with evidence. Start coaching here.",
)
add(
    "get_training_summary",
    "coaching",
    "GET",
    "/training/summary",
    AnalyticsQuery,
    TrainingSummaryRead,
    "Weekly sessions, load, run km/pace, strength volume, hard sets per muscle and plan adherence.",
)
add(
    "get_training_load",
    "coaching",
    "GET",
    "/training/load",
    AnalyticsQuery,
    TrainingLoadRead,
    "Daily sRPE load with acute 7d, chronic 28d, ACWR, monotony and strain.",
)
add(
    "get_strength_progress",
    "coaching",
    "GET",
    "/training/strength/progress",
    StrengthProgressQuery,
    StrengthProgressRead,
    "Per-session top set, best e1RM, volume and 4-week e1RM change for one exercise.",
)
add(
    "get_strength_records",
    "coaching",
    "GET",
    "/training/strength/records",
    TimezoneQuery,
    StrengthRecordsRead,
    "All-time best e1RM and 1/3/5/10 rep maxes per exercise.",
)
add(
    "get_running_summary",
    "coaching",
    "GET",
    "/training/running/summary",
    AnalyticsQuery,
    RunningSummaryRead,
    "Weekly running km, longest run, pace by workout type, easy share, best efforts and race predictions.",
)

# Dữ liệu thiết bị đồng bộ từ Google Health (chỉ đọc). Kết nối và đồng bộ là
# thao tác của người dùng trong Cài đặt, không bao giờ là tool; lệnh đọc trả 403 consent_required khi
# người dùng chưa cho phép trợ lý dùng dữ liệu.
add(
    "get_health_connection",
    "health",
    "GET",
    "/integrations/google-health",
    Empty,
    HealthConnectionRead,
    "Whether Google Health is connected, consent to share with the assistant, last sync and record counts. Check this when health data is missing.",
)
add(
    "get_health_profile",
    "health",
    "GET",
    "/health/profile",
    TimezoneQuery,
    HealthProfileRead,
    "Unified health profile: each value with its source (DECLARED/MEASURED/PROVIDER/DERIVED), BMI class (Asian cut-offs), "
    "measured resting HR, observed vs declared activity level, missing fields and declared-vs-measured conflicts.",
)
add(
    "get_health_overview",
    "health",
    "GET",
    "/health/overview",
    HealthOverviewQuery,
    HealthOverviewRead,
    "Deterministic analysis over the last N days: steps, active minutes vs WHO 150/week, sleep duration/stages/regularity, "
    "resting HR and HRV against the 28-day baseline, and logged intake vs device expenditure. Start health questions here.",
)
add(
    "list_daily_health",
    "health",
    "GET",
    "/health/daily",
    DateRangeQuery,
    list[DailyHealthRead],
    "Per-day device rollups (steps, distance, active minutes, total kcal, resting HR, HRV, SpO2, sleep minutes) for start_date..end_date.",
)
add(
    "list_sleep_sessions",
    "health",
    "GET",
    "/health/sleep",
    DateRangeQuery,
    list[SleepSessionRead],
    "Sleep sessions (bedtime, wake time, minutes asleep, deep/light/REM minutes, efficiency, naps) for start_date..end_date.",
)
add(
    "list_device_workouts",
    "health",
    "GET",
    "/health/workouts",
    DateRangeQuery,
    list[DeviceWorkoutRead],
    "Workouts recorded by a device (type, duration, distance, kcal, average HR) for start_date..end_date. Not training-log entries.",
)
add(
    "list_health_samples",
    "health",
    "GET",
    "/health/samples",
    HealthSampleQuery,
    list[HealthSampleRead],
    "Spot vitals (BLOOD_GLUCOSE mg/dL, CORE_BODY_TEMPERATURE °C) for start_date..end_date. Report values; never diagnose.",
)

# Ngữ cảnh sức khoẻ có nguồn, có ngân sách (backend /api/v2/assistant/context): mỗi mục mang
# giá trị, đơn vị, nguồn, measured_at, độ mới, độ phủ, phương pháp và id bằng chứng.

_Topic = Literal["overview", "activity", "sleep", "recovery", "body", "nutrition", "vitals"]
_Period = Literal["7d", "28d", "90d"]


class HealthContextQuery(InputSchema):
    topic: _Topic = "overview"
    period: _Period = "28d"
    budget: int = Field(default=1500, ge=200, le=3000)


class HealthContextDeepQuery(InputSchema):
    topics: list[_Topic] = Field(min_length=1, max_length=8)
    period: _Period = "28d"
    budget: int = Field(default=4000, ge=200, le=8000)


add(
    "get_health_context",
    "health",
    "GET",
    "/v2/assistant/context",
    HealthContextQuery,
    dict[str, Any],
    "Precomputed health context with provenance (value, unit, source, measured_at, freshness, coverage, method). "
    "Prefer this over raw lists; use the numbers as given, never recompute them, and treat missing coverage as unknown.",
)
add(
    "query_health_context",
    "health",
    "GET",
    "/v2/assistant/context:query",
    HealthContextDeepQuery,
    dict[str, Any],
    "Deeper context for several topics within a token budget (default 4000). vitals needs separate consent; "
    "ECG is the device classification only: report it, never diagnose.",
)

# Daily Health Intelligence (backend domains/analytics/services/daily_health): chỉ số hôm nay so với nền cá nhân,
# xu hướng 7 ngày, tải tập và trạng thái sẵn sàng tất định kèm lý do có số liệu và độ tin cậy.


class DailyAssessmentQuery(TimezoneQuery):
    date: _date | None = Field(default=None, description="Local day to assess; omit for today")


add(
    "get_health_assessment",
    "health",
    "GET",
    "/v2/health/daily-assessment",
    DailyAssessmentQuery,
    DailyAssessmentRead,
    "Deterministic daily assessment: last night sleep, HRV, resting HR, SpO2, breathing and skin temperature against "
    "the user's own 28-day baseline, 7-day trends, training load, and a readiness state (ready, steady, ease_off, "
    "recover, needs_review, insufficient_data) with numeric reasons and confidence. Start questions about today, "
    "recovery or whether to train hard here. Report it as given; never recompute, never diagnose.",
)
HEALTH_TOOL_KINDS = {
    "list_daily_health": "DailyHealth",
    "list_sleep_sessions": "SleepSession",
    "list_device_workouts": "DeviceWorkout",
}

# Ghi xuyên qua lên Google Health (Google là nguồn sự thật, HercFit không giữ bản riêng):
# buổi thể thao (mọi môn không phải gym), nước uống và giấc ngủ ghi tay. Gym vẫn là create_trainings.

add(
    "log_sport_session",
    "trainings",
    "POST",
    "/v2/health/records/exercise",
    SportInput,
    HealthRecordRead,
    "Propose logging a NON-gym sport or cardio session (running, football, badminton, swimming...) to Google Health. "
    "exercise_id is a SPORT/ENDURANCE catalog exercise and performance has the same shape as a training item; "
    "kcal is estimated by the backend. Gym sessions use create_trainings. Must await human confirmation.",
    True,
)
add(
    "update_sport_session",
    "trainings",
    "PATCH",
    "/v2/health/records/exercise/{resource_id}",
    with_id(SportInput),
    HealthRecordRead,
    "Replace a sport session HercFit wrote to Google (ids from list_device_workouts). "
    "Sessions recorded by a device cannot be edited.",
    True,
)
add(
    "delete_sport_session",
    "trainings",
    "DELETE",
    "/v2/health/records/exercise/{resource_id}",
    Resource,
    None,
    "Delete a sport session HercFit wrote to Google after confirmation.",
)
add(
    "log_water",
    "meals",
    "POST",
    "/v2/health/records/hydration",
    HydrationInput,
    HealthRecordRead,
    "Propose logging water intake in ml to Google Health. Must await human confirmation.",
    True,
)
add(
    "delete_water",
    "meals",
    "DELETE",
    "/v2/health/records/hydration/{resource_id}",
    Resource,
    None,
    "Delete a water log HercFit wrote to Google after confirmation.",
)
# Giấc ngủ ghi tay thuộc metrics (body_health ghi); domain health giữ nguyên chỉ đọc.
add(
    "log_sleep",
    "metrics",
    "POST",
    "/v2/health/records/sleep",
    SleepInput,
    HealthRecordRead,
    "Propose logging a night of sleep the user reports (bedtime started_at, wake time ended_at, timezone) to Google "
    "Health, for nights the device did not record. Only what the user said: no stages or awakenings. A night the "
    "device already recorded is refused (409). Must await human confirmation.",
    True,
)
add(
    "delete_sleep",
    "metrics",
    "DELETE",
    "/v2/health/records/sleep/{resource_id}",
    Resource,
    None,
    "Delete a sleep entry HercFit wrote to Google (ids from list_sleep_sessions) after confirmation.",
)


# Các lệnh ghi mà thẻ xác nhận cần tổng do server tính, ảnh chụp dữ liệu và hình ảnh.
PREVIEW_PATHS = {
    "create_meals": "/api/meals/preview",
    "create_trainings": "/api/trainings/preview",
    "create_training_plans": "/api/training-plans/preview",
    "update_training_plans": "/api/training-plans/{resource_id}/preview",
    "log_sport_session": "/api/v2/health/records/exercise:preview",
    "log_water": "/api/v2/health/records/hydration:preview",
    "log_sleep": "/api/v2/health/records/sleep:preview",
}
