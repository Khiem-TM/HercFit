"""Centralized SQLAlchemy 2.0 ORM models registry."""

from core.database import Base
from domains.identity.models.auth_session import AuthSession
from domains.shared.models.basemodel import BaseModel
from domains.body.models.body_metrics import BodyMetric
from domains.catalog.models.foods import FoodItem, FoodItemType, FoodServingUnit, FoodSourceType
from domains.goals_plans.models.goal import Goal, GoalStatus
from domains.identity.models.oauth_account import OAuthAccount
from domains.identity.models.user import User
from domains.identity.models.consent import ConsentEvent, UserConsent
from domains.catalog.models.exercises import Exercise
from domains.goals_plans.models.plans import (
    Plan,
    MealPlan,
    MealPlanEntry,
    MealPlanItem,
    TrainingPlan,
    TrainingPlanEntry,
    TrainingPlanItem,
)
from domains.nutrition.models.meals import Meal, MealItem
from domains.training.models.trainings import Training, TrainingItem
from domains.media.models.media import ImageCleanup
from domains.health_records.models.sources import HealthRecordLink, HealthSeriesChunk, HealthSourceRecord
from domains.health_records.models.device_records import DailyHealthSummary, DeviceWorkout, HealthSample, SleepSession
from domains.health_records.models.clinical import EcgRecording, IrnAlert, PairedDevice, WorkoutRoute
from domains.nutrition.models.logs import HydrationLog, NutritionLog
from domains.wellbeing.models.logs import MenstrualPeriodLog, MoodLog, OvulationTestLog, SymptomLog
from integrations.google_health.models import HealthConnection, HealthSyncRun
from core.graph_outbox import register_metadata_hooks

register_metadata_hooks(Base.metadata)

__all__ = [
    "HealthSourceRecord", "HealthSeriesChunk", "HealthRecordLink",
    "EcgRecording", "IrnAlert", "PairedDevice", "WorkoutRoute", "HydrationLog", "NutritionLog",
    "MenstrualPeriodLog", "MoodLog", "OvulationTestLog", "SymptomLog",
    "UserConsent", "ConsentEvent",
    "Base",
    "BaseModel",
    "User",
    "OAuthAccount",
    "AuthSession",
    "BodyMetric",
    "Goal",
    "GoalStatus",
    "FoodItem",
    "FoodItemType",
    "FoodServingUnit",
    "FoodSourceType",
    "Exercise", "Plan", "MealPlan", "MealPlanEntry", "MealPlanItem",
    "TrainingPlan", "TrainingPlanEntry", "TrainingPlanItem",
    "Meal", "MealItem", "Training", "TrainingItem",
    "HealthConnection", "HealthSyncRun", "DailyHealthSummary", "SleepSession", "DeviceWorkout", "HealthSample",
]
