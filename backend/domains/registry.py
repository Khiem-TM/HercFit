"""Registry tập trung các model ORM SQLAlchemy 2.0."""

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
from domains.health_records.models.health_points import HealthPoint
from integrations.google_health.models import GooglePush, HealthConnection
from core.graph_outbox import register_metadata_hooks

register_metadata_hooks(Base.metadata)

__all__ = [
    "HealthPoint", "GooglePush",
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
    "HealthConnection",
]
