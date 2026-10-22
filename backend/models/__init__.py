"""Centralized SQLAlchemy 2.0 ORM models registry."""

from core.database import Base
from models.auth_session import AuthSession
from models.basemodel import BaseModel
from models.body_metrics import BodyMetric
from models.foods import FoodItem, FoodItemType, FoodServingUnit, FoodSourceType
from models.goal import Goal, GoalStatus
from models.oauth_account import OAuthAccount
from models.user import User
from models.exercises import Exercise
from models.plans import Plan, MealPlan, MealPlanEntry, MealPlanItem, TrainingPlan, TrainingPlanEntry, TrainingPlanItem
from models.journals import Meal, MealItem, Training, TrainingItem
from core.graph_outbox import register_metadata_hooks

register_metadata_hooks(Base.metadata)

__all__ = [
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
]
