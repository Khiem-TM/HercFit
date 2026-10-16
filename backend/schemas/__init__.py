"""Pydantic v2 DTO schemas package for domain CRUD layers."""

from schemas.habit import (
    HabitCheckInCreate,
    HabitCheckInResponse,
    HabitCreate,
    HabitResponse,
)
from schemas.nutrition import DailyNutritionSummary, MealCreate, MealResponse
from schemas.user import (
    BodyMetricCreate,
    BodyMetricResponse,
    UserProfileResponse,
    UserProfileUpdate,
)
from schemas.workout import (
    ExerciseItem,
    WorkoutPlanCreate,
    WorkoutPlanResponse,
    WorkoutSessionCreate,
    WorkoutSessionResponse,
)

__all__ = [
    "UserProfileUpdate",
    "UserProfileResponse",
    "BodyMetricCreate",
    "BodyMetricResponse",
    "MealCreate",
    "MealResponse",
    "DailyNutritionSummary",
    "ExerciseItem",
    "WorkoutPlanCreate",
    "WorkoutPlanResponse",
    "WorkoutSessionCreate",
    "WorkoutSessionResponse",
    "HabitCreate",
    "HabitResponse",
    "HabitCheckInCreate",
    "HabitCheckInResponse",
]

