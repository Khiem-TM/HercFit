"""Allowlisted API tools. Input and output types are the backend's actual contracts."""
from uuid import UUID
from agentic.tools.definitions.base import ToolSpec
from agentic.tools.schemas.common import Empty, Resource, VersionedResource, PersonalInfo, TimezoneQuery, TemplatePreview
from pydantic import create_model
from domains.shared.schemas.common import Pagination
from domains.identity.schemas.user import UserRead, UserUpdate, OnboardingInput
from domains.body.schemas.body_metrics import BodyMetricCreate, BodyMetricRead, BodyMetricQuery
from domains.goals_plans.schemas.goal import GoalCreate, GoalRead, GoalUpdateRequest
from domains.catalog.schemas.foods import FoodCreate, FoodRead, FoodQuery
from domains.catalog.schemas.exercises import ExerciseCreate, ExerciseRead, ExerciseQuery
from domains.nutrition.schemas.meals import MealCreate, MealReplace, MealRead
from domains.training.schemas.trainings import TrainingCreate, TrainingReplace, TrainingRead
from domains.shared.schemas.tracking import JournalQuery, DateRangeQuery
from domains.analytics.schemas.progress import ProgressRead


REGISTRY: dict[str, ToolSpec] = {}

def add(name, domain, method, path, schema, output, description, body=False):
    REGISTRY[name] = ToolSpec(name, domain, method, '/api' + path, schema, output, description, body)

def with_id(schema):
    return create_model(schema.__name__ + 'WithID', __base__=schema, resource_id=(UUID, ...))

add('get_profile','profile','GET','/profile',Empty,UserRead,'Read authenticated profile.')
add('update_profile','profile','PATCH','/profile',UserUpdate,UserRead,'Update only supplied profile fields.',True)
# Root object merge is unwrapped by the client; identity fields are never accepted.
add('merge_personal_info','profile','PATCH','/profile/personal-info',PersonalInfo,UserRead,'Merge top-level personal_info groups; nested groups replace as a whole.',True)
add('onboard','profile','POST','/profile/onboarding',OnboardingInput,UserRead,'Save confirmed onboarding profile, optional metric and goal atomically.',True)
for domain,path,create,read,query,replace in [
    ('metrics','body-metrics',BodyMetricCreate,BodyMetricRead,BodyMetricQuery,BodyMetricCreate),
    ('goals','goals',GoalCreate,GoalRead,Pagination,GoalUpdateRequest),
    ('meals','meals',MealCreate,MealRead,JournalQuery,MealReplace),
    ('trainings','trainings',TrainingCreate,TrainingRead,JournalQuery,TrainingReplace),
    ('foods','foods',FoodCreate,FoodRead,FoodQuery,None),
    ('exercises','exercises',ExerciseCreate,ExerciseRead,ExerciseQuery,None),
]:
    add('list_'+domain,domain,'GET','/'+path,query,list[read],'Search/list '+domain+' with filters and pagination. Empty list means no match.')
    add('get_'+domain,domain,'GET','/'+path+'/{resource_id}',Resource,read,'Read a specific '+domain+' record.')
    add('create_'+domain,domain,'POST','/'+path+('/confirm' if domain=='goals' else ''),create,read,'Propose creation of '+domain+'. Must await human confirmation.',True)
    if replace:
        add('update_'+domain,domain,'PATCH' if domain=='goals' else 'PUT','/'+path+'/{resource_id}',with_id(replace),read,
            'Replace snapshot (returns NEW ID) or patch goal. Read existing record first; preserve omitted snapshot values explicitly.',True)
        add('delete_'+domain,domain,'DELETE','/'+path+'/{resource_id}',VersionedResource if domain in {'meals','trainings'} else Resource,None,'Soft delete the specified record after confirmation.')
add('latest_metrics','metrics','GET','/body-metrics/latest',Empty,BodyMetricRead,'Read latest measurement; 404 means no measurements.')
add('current_goal','goals','GET','/goals/current',Empty,GoalRead,'Read active goal; 404 means no active goal.')
for action in ['complete','cancel']:
    add(action+'_goal','goals','POST','/goals/{resource_id}/'+action,Resource,GoalRead,action+' the active goal after confirmation.')
add('get_progress','progress','GET','/progress',DateRangeQuery,ProgressRead,'Read daily progress for explicit start_date/end_date and timezone.')

# Research finalizations use the same preview/hash/approval adapter as other writes.
from agentic.research.contracts import ResolveQuery, FoodFinalization, ExerciseFinalization
for domain, schema in [('foods', FoodFinalization), ('exercises', ExerciseFinalization)]:
    add('resolve_'+domain, domain, 'GET', '/'+domain+'/resolve', ResolveQuery, dict,
        'Resolve exact catalog identities, aliases and possible variants before research.')
    add('finalize_'+domain, domain, 'POST', '/'+domain+'/research-finalizations', schema, dict,
        'Save the immutable verified research command after human confirmation.', True)

# Training plans (prescriptions) and deterministic coaching analytics.
from domains.goals_plans.schemas.plans import (
    PlanInput,
    PlanRead,
    PlanEnd,
    TrainingPlanCreate,
    TrainingPlanRead,
    TrainingPlanReplace,
    TrainingPlanEntryRead,
)
from domains.shared.schemas.tracking import ScheduleEntryQuery
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


add('current_plan','training_plans','GET','/plans/current',Empty,PlanRead,'Read the active parent plan; its id is required to create a training schedule. 404 means none.')
add('create_plan','training_plans','POST','/plans',PlanInput,PlanRead,
    'Propose the parent plan when current_plan is 404: goal_id from current_goal, name, start_date, end_date covering the schedule. Must await confirmation.',True)
add('current_training_plan','training_plans','GET','/plans/{resource_id}/training-plans/current',Resource,TrainingPlanRead,'Read the active training schedule of a parent plan (resource_id = plan id).')
add('get_training_plans','training_plans','GET','/training-plans/{resource_id}',Resource,TrainingPlanRead,'Read one training schedule.')
add('list_training_plan_entries','training_plans','GET','/training-plans/{resource_id}/entries',with_id(ScheduleEntryQuery),list[TrainingPlanEntryRead],
    'List scheduled sessions (optionally on_date or start/end date) of a training schedule.')
add('list_training_templates','training_plans','GET','/training/templates',Empty,list[TemplateSummary],'List program templates (Gym/Running/Hybrid) and single running workouts.')
add('preview_training_template','training_plans','GET','/training/templates/{resource_id}/schedule',TemplatePreview,TrainingPlanCreate,
    'Build a schedule preview from a program template. Read-only; pass the returned payload unchanged to create_training_plans.')
add('create_training_plans','training_plans','POST','/plans/{resource_id}/training-plans',with_id(TrainingPlanCreate),TrainingPlanRead,
    'Propose a training schedule for parent plan resource_id. Items use prescription (targets), not performance. Must await confirmation.',True)
add('update_training_plans','training_plans','PUT','/training-plans/{resource_id}',with_id(TrainingPlanReplace),TrainingPlanRead,
    'Replace a training schedule as a complete new version. Read it first. Must await confirmation.',True)
add('end_training_plan','training_plans','POST','/training-plans/{resource_id}/end',with_id(PlanEnd),TrainingPlanRead,'End a training schedule after confirmation.',True)

from domains.nutrition.schemas.nutrition import NutritionTargetsRead
add('get_nutrition_targets','progress','GET','/nutrition/targets',TimezoneQuery,NutritionTargetsRead,
    'Daily energy and macro targets computed by the backend (Mifflin-St Jeor BMR, TDEE, goal adjustment with safety '
    'floors), kcal eaten and remaining today, smoothed weight trend and adaptive expenditure. Never compute these yourself.')
add('get_training_profile','coaching','GET','/training/profile',Empty,TrainingProfileRead,'Athlete profile with HR zones, pace zones and race predictions.')
add('update_training_profile','coaching','PUT','/training/profile',TrainingProfile,TrainingProfileRead,'Replace the athlete profile (level, focus, HR, threshold pace, recent race, 1RMs). Must await confirmation.',True)
add('get_training_insights','coaching','GET','/training/insights',InsightQuery,InsightsRead,
    'Deterministic findings (overload/ACWR, mileage jump, no rest, intensity mix, muscle volume, plateau, PR, adherence, fueling) with evidence. Start coaching here.')
add('get_training_summary','coaching','GET','/training/summary',AnalyticsQuery,TrainingSummaryRead,'Weekly sessions, load, run km/pace, strength volume, hard sets per muscle and plan adherence.')
add('get_training_load','coaching','GET','/training/load',AnalyticsQuery,TrainingLoadRead,'Daily sRPE load with acute 7d, chronic 28d, ACWR, monotony and strain.')
add('get_strength_progress','coaching','GET','/training/strength/progress',StrengthProgressQuery,StrengthProgressRead,'Per-session top set, best e1RM, volume and 4-week e1RM change for one exercise.')
add('get_strength_records','coaching','GET','/training/strength/records',TimezoneQuery,StrengthRecordsRead,'All-time best e1RM and 1/3/5/10 rep maxes per exercise.')
add('get_running_summary','coaching','GET','/training/running/summary',AnalyticsQuery,RunningSummaryRead,'Weekly running km, longest run, pace by workout type, easy share, best efforts and race predictions.')

# Device data synchronized from Google Health (read-only). Connecting and syncing are
# the user's actions in Settings, never tools; reads answer 403 consent_required while
# the user has not allowed the assistant to use the data.
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
from integrations.google_health.schemas import HealthConnectionRead
add('get_health_connection','health','GET','/integrations/google-health',Empty,HealthConnectionRead,
    'Whether Google Health is connected, consent to share with the assistant, last sync and record counts. Check this when health data is missing.')
add('get_health_profile','health','GET','/health/profile',TimezoneQuery,HealthProfileRead,
    'Unified health profile: each value with its source (DECLARED/MEASURED/PROVIDER/DERIVED), BMI class (Asian cut-offs), '
    'measured resting HR, observed vs declared activity level, missing fields and declared-vs-measured conflicts.')
add('get_health_overview','health','GET','/health/overview',HealthOverviewQuery,HealthOverviewRead,
    'Deterministic analysis over the last N days: steps, active minutes vs WHO 150/week, sleep duration/stages/regularity, '
    'resting HR and HRV against the 28-day baseline, and logged intake vs device expenditure. Start health questions here.')
add('list_daily_health','health','GET','/health/daily',DateRangeQuery,list[DailyHealthRead],
    'Per-day device rollups (steps, distance, active minutes, total kcal, resting HR, HRV, SpO2, sleep minutes) for start_date..end_date.')
add('list_sleep_sessions','health','GET','/health/sleep',DateRangeQuery,list[SleepSessionRead],
    'Sleep sessions (bedtime, wake time, minutes asleep, deep/light/REM minutes, efficiency, naps) for start_date..end_date.')
add('list_device_workouts','health','GET','/health/workouts',DateRangeQuery,list[DeviceWorkoutRead],
    'Workouts recorded by a device (type, duration, distance, kcal, average HR) for start_date..end_date. Not training-log entries.')
add('list_health_samples','health','GET','/health/samples',HealthSampleQuery,list[HealthSampleRead],
    'Spot vitals (BLOOD_GLUCOSE mg/dL, CORE_BODY_TEMPERATURE °C) for start_date..end_date. Report values; never diagnose.')
HEALTH_TOOL_KINDS = {'list_daily_health': 'DailyHealth', 'list_sleep_sessions': 'SleepSession',
                     'list_device_workouts': 'DeviceWorkout'}
