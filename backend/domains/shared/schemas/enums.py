"""Value types shared by schemas and SQLAlchemy models, without ORM imports."""

from enum import StrEnum


class FoodSourceType(StrEnum):
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"


class FoodItemType(StrEnum):
    FOOD = "FOOD"
    DISH = "DISH"


class FoodServingUnit(StrEnum):
    """Basis of the stored nutrient values: per serving_size grams, millilitres,
    or per PORTION (one serving/suất whose gram weight may be unknown)."""
    G = "G"
    ML = "ML"
    PORTION = "PORTION"


class GoalStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
