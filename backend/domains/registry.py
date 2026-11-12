"""Registry tập trung các model ORM SQLAlchemy 2.0."""

from core.database import Base
from core.graph_outbox import register_metadata_hooks
from domains.body.models.body_metrics import BodyMetric
from domains.catalog.models.exercises import Exercise
from domains.catalog.models.foods import FoodItem, FoodItemType, FoodServingUnit, FoodSourceType
from domains.goals_plans.models.goal import Goal, GoalStatus
from domains.goals_plans.models.plans import (
    Plan,
    TrainingPlan,
    TrainingPlanEntry,
    TrainingPlanItem,
)
from domains.health_records.models.health_points import HealthPoint
from domains.identity.models.auth_session import AuthSession
from domains.identity.models.consent import ConsentEvent, UserConsent
from domains.identity.models.oauth_account import OAuthAccount
from domains.identity.models.user import User
from domains.media.models.media import ImageCleanup  # noqa: F401 (đăng ký bảng vào Base.metadata)
from domains.notifications.models.notification import UserNotification
from domains.nutrition.models.meals import Meal, MealItem
from domains.shared.models.basemodel import BaseModel
from domains.training.models.trainings import Training, TrainingItem
from integrations.google_health.models import GooglePush, HealthConnection

register_metadata_hooks(Base.metadata)

__all__ = [
    "HealthPoint", "GooglePush", "UserNotification",
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
    "Exercise", "Plan",
    "TrainingPlan", "TrainingPlanEntry", "TrainingPlanItem",
    "Meal", "MealItem", "Training", "TrainingItem",
    "HealthConnection",
]
