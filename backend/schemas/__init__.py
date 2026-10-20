"""Public backend contracts. Safe to import without starting the application."""

from schemas.auth_session import (
    AuthSessionCreate,
    AuthSessionRead,
    AuthSessionRevoke,
    LogoutResponse,
    TokenResponse,
)
from schemas.body_metrics import BodyMetricCreate, BodyMetricQuery, BodyMetricRead, BodyMetricReplace
from schemas.common import Pagination, UserScope, VersionCheck
from schemas.foods import FoodCreate, FoodQuery, FoodRead, FoodUpdate, FoodUpdateRequest, SystemFoodCreate
from schemas.goal import GoalCreate, GoalRead, GoalUpdate, GoalUpdateRequest
from schemas.oauth_account import OAuthAccountCreate, OAuthAccountRead, OAuthTokenUpdate
from schemas.user import GoogleProfile, OnboardingInput, UserCreate, UserRead, UserUpdate
from schemas.exercises import ExerciseCreate, SystemExerciseCreate, ExerciseUpdateRequest, ExerciseRead, ExerciseQuery, ExerciseActivityInput, CalorieEstimate
from schemas.plans import PlanInput, ManualPlanReplace, PlanCreate, PlanReplace, PlanEnd, PlanRead, PlanQuery, MealPlanCreate, MealPlanReplace, MealPlanRead, TrainingPlanCreate, TrainingPlanReplace, TrainingPlanRead
from schemas.journals import MealCreate, MealReplace, MealRead, TrainingCreate, TrainingReplace, TrainingRead
from schemas.tracking import DateRangeQuery, JournalQuery, ScheduleEntryQuery, ProgressRangeQuery
from schemas.progress import DailyProgressRead, MetricProgress, PlanProgressRead, ProgressRead

__all__ = [
    "AuthSessionCreate", "AuthSessionRead", "AuthSessionRevoke", "LogoutResponse", "TokenResponse",
    "BodyMetricCreate", "BodyMetricQuery", "BodyMetricRead", "BodyMetricReplace",
    "Pagination", "UserScope", "VersionCheck",
    "FoodCreate", "FoodQuery", "FoodRead", "FoodUpdate", "FoodUpdateRequest", "SystemFoodCreate",
    "GoalCreate", "GoalRead", "GoalUpdate", "GoalUpdateRequest",
    "OAuthAccountCreate", "OAuthAccountRead", "OAuthTokenUpdate",
    "GoogleProfile", "OnboardingInput", "UserCreate", "UserRead", "UserUpdate",
    "ExerciseCreate", "SystemExerciseCreate", "ExerciseUpdateRequest", "ExerciseRead", "ExerciseQuery", "ExerciseActivityInput", "CalorieEstimate",
    "PlanInput", "ManualPlanReplace", "PlanCreate", "PlanReplace", "PlanEnd", "PlanRead", "PlanQuery",
    "MealPlanCreate", "MealPlanReplace", "MealPlanRead", "TrainingPlanCreate", "TrainingPlanReplace", "TrainingPlanRead",
    "MealCreate", "MealReplace", "MealRead", "TrainingCreate", "TrainingReplace", "TrainingRead", "DateRangeQuery", "JournalQuery",
    "DailyProgressRead", "MetricProgress", "PlanProgressRead", "ProgressRead", "ScheduleEntryQuery", "ProgressRangeQuery",
]
