"""Registry tập trung các model ORM SQLAlchemy 2.0."""

from core.database import Base
from core.graph_outbox import register_metadata_hooks
from domains.body.models import BodyMetric
from domains.catalog.models import Exercise, FoodItem, FoodItemType, FoodServingUnit, FoodSourceType
from domains.goals_plans.models import (
    Goal,
    GoalStatus,
    Plan,
    TrainingPlan,
    TrainingPlanEntry,
    TrainingPlanItem,
)
from domains.health_records.models import HealthPoint
from domains.identity.models import AuthSession, ConsentEvent, OAuthAccount, User, UserConsent
from domains.media.models import ImageCleanup  # noqa: F401 (đăng ký bảng vào Base.metadata)
from domains.notifications.models import UserNotification
from domains.nutrition.models import Meal, MealItem
from domains.shared.models import BaseModel
from domains.training.models import Training, TrainingItem
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
