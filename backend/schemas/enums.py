"""Value types shared by schemas and SQLAlchemy models, without ORM imports."""

from enum import StrEnum


class FoodSourceType(StrEnum):
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"


class FoodItemType(StrEnum):
    FOOD = "FOOD"
    DISH = "DISH"


class FoodServingUnit(StrEnum):
    G = "G"
    ML = "ML"


class GoalStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
