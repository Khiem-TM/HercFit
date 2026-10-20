"""Pydantic schemas validating user, health calculation, and catalog tool inputs/outputs."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthMetricsCalcInput(BaseModel):
    """Input schema for calculating BMI, BMR, TDEE, and daily macro targets."""

    weight_kg: float = Field(gt=20, le=350, description="Body weight in kilograms (kg).")
    height_cm: float = Field(gt=80, le=260, description="Body height in centimeters (cm).")
    age: int = Field(ge=10, le=110, description="Age in years.")
    gender: Literal["male", "female"] = Field(
        default="male", description="Biological sex for Mifflin-St Jeor BMR formula."
    )
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] = Field(
        default="moderate",
        description="Daily physical activity level.",
    )
    goal_type: Literal["lose_weight", "maintain", "gain_muscle"] = Field(
        default="maintain",
        description="Primary fitness goal for calorie & macro calculation.",
    )


class HealthMetricsCalcOutput(BaseModel):
    """Calculated health metrics and daily macro recommendations."""

    bmi: float
    bmi_category: str
    bmr_kcal: float
    tdee_kcal: float
    target_calories_kcal: float
    macros_g: dict[str, float]


class MathExpressionInput(BaseModel):
    """Input schema for safe mathematical expression evaluation."""

    expression: str = Field(
        min_length=1,
        max_length=200,
        description="Arithmetic expression to evaluate, e.g., '(75 * 2.2) + 500'.",
    )


class KnowledgeSearchInput(BaseModel):
    """Input schema for querying internal fitness & nutrition knowledge."""

    query: str = Field(
        min_length=2,
        max_length=300,
        description="Search query about exercise technique, nutrition, or recovery.",
    )


class BodyMetricLogInput(BaseModel):
    """Input schema for logging a new body metric snapshot to the Backend."""

    weight_kg: float = Field(gt=20, le=350, description="Current body weight in kg.")
    height_cm: float | None = Field(
        default=None, gt=80, le=260, description="Optional height in cm."
    )
    body_fat_pct: float | None = Field(
        default=None, ge=2, le=70, description="Optional body fat percentage."
    )
    auth_token: str | None = Field(
        default=None, description="Optional Bearer JWT token."
    )


class CatalogSearchInput(BaseModel):
    """Input schema for searching foods or exercises in the Backend catalog."""

    search: str = Field(
        min_length=1,
        max_length=120,
        description="Keyword to search for foods or exercises.",
    )
    limit: int = Field(default=5, ge=1, le=50, description="Maximum items to return.")
    auth_token: str | None = Field(
        default=None, description="Optional Bearer JWT token."
    )

