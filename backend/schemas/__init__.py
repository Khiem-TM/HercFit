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
from schemas.foods import FoodCreate, FoodQuery, FoodRead, FoodUpdate, SystemFoodCreate
from schemas.goal import GoalCreate, GoalRead, GoalUpdate, GoalUpdateRequest
from schemas.oauth_account import OAuthAccountCreate, OAuthAccountRead, OAuthTokenUpdate
from schemas.user import GoogleProfile, OnboardingInput, UserCreate, UserRead, UserUpdate

__all__ = [
    "AuthSessionCreate", "AuthSessionRead", "AuthSessionRevoke", "LogoutResponse", "TokenResponse",
    "BodyMetricCreate", "BodyMetricQuery", "BodyMetricRead", "BodyMetricReplace",
    "Pagination", "UserScope", "VersionCheck",
    "FoodCreate", "FoodQuery", "FoodRead", "FoodUpdate", "SystemFoodCreate",
    "GoalCreate", "GoalRead", "GoalUpdate", "GoalUpdateRequest",
    "OAuthAccountCreate", "OAuthAccountRead", "OAuthTokenUpdate",
    "GoogleProfile", "OnboardingInput", "UserCreate", "UserRead", "UserUpdate",
]
