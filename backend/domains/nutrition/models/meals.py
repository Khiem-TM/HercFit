"""Aggregate hoạt động thực tế bất biến với sửa nguyên tử và lệnh đọc có phạm vi.

Tách ra từ models.journals trong đợt tổ chức lại theo miền."""
from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domains.nutrition.schemas.meals import MealCreate
from domains.shared.models.activity import (
    FoodPortionMixin,
    NutrientColumns,
    build_food_item,
    food_item_constraints,
    nutrient_constraints,
    sum_known,
)
from domains.shared.models.basemodel import BaseModel
from domains.shared.models.domain import guard_immutable
from domains.shared.models.journal import Journal, journal_constraints
from domains.shared.schemas.activity import NutritionTotals


class Meal(NutrientColumns, Journal):
    __tablename__ = "meals"
    __table_args__ = (
        *journal_constraints("meals"), *nutrient_constraints("meals"),
        Index("ix_meals_user_consumed", "user_id", "consumed_at", "id"),
        UniqueConstraint("replaces_id", name="uq_meals_replaces"),
    )
    TIME_FIELD = "consumed_at"
    CREATE_SCHEMA = MealCreate

    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meals.id", ondelete="RESTRICT"), nullable=True)
    nutrition_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    items: Mapped[list["MealItem"]] = relationship(back_populates="meal", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin", order_by="MealItem.position")

    @classmethod
    async def _insert_snapshot(cls, session, *, user_id, data, replaces_id=None):
        items = [await build_food_item(session, user_id, item) for item in data.items]
        totals = NutritionTotals.model_validate(sum_known(items)).model_dump()
        entity = cls(
            **data.model_dump(exclude={"items"}), user_id=user_id, replaces_id=replaces_id,
            **totals, nutrition_incomplete=any(value is None for value in totals.values()),
            items=[MealItem(**item, position=position) for position, item in enumerate(items)],
        )
        session.add(entity)
        await session.flush()
        return entity

class MealItem(FoodPortionMixin, BaseModel):
    __tablename__ = "meal_items"
    __table_args__ = (*food_item_constraints("meal_items"), UniqueConstraint("meal_id", "position", name="uq_meal_items_position"))
    meal_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meals.id", ondelete="CASCADE"), nullable=False)
    meal: Mapped[Meal] = relationship(back_populates="items")


guard_immutable(Meal, allowed=("image_url", "image_public_id"))
guard_immutable(MealItem, allowed=())
