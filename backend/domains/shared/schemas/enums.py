"""Kiểu giá trị dùng chung cho schema và model SQLAlchemy, không import ORM."""

from enum import StrEnum


class FoodSourceType(StrEnum):
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"


class FoodItemType(StrEnum):
    FOOD = "FOOD"
    DISH = "DISH"


class FoodServingUnit(StrEnum):
    """Basis of the stored nutrient values: per serving_size grams or millilitres."""
    G = "G"
    ML = "ML"


class GoalStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
