"""Immutable actual activity aggregates with atomic correction and scoped reads."""

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID as PyUUID

from fastapi import HTTPException
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from models.activity import FoodPortionMixin, ExerciseActivityMixin, NutrientColumns, build_food_item, build_exercise_item, food_item_constraints, exercise_item_constraints, nutrient_constraints, sum_known
from models.basemodel import BaseModel
from models.domain import guard_immutable, lock_user, require_version
from schemas.activity import NutritionTotals
from schemas.common import UserScope
from schemas.journals import MealCreate, TrainingCreate
from schemas.tracking import JournalQuery

# Lớp cơ sở cho các nhật ký hoạt động thực tế (Training và Meal) --> Đều có tính chất ghi và kế thừa lại Object này
class Journal(BaseModel):
    __abstract__ = True
    TIME_FIELD: ClassVar[str]
    CREATE_SCHEMA: ClassVar[Any]

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="USER", server_default="USER", nullable=False)
    detail_status: Mapped[str] = mapped_column(String(20), default="DETAILED", server_default="DETAILED", nullable=False)

    @classmethod
    def _query(cls, user_id, *, include_inactive=False):
        user_id = UserScope(user_id=user_id).user_id
        return cls.apply_active_scope(
            select(cls).where(cls.user_id == user_id).options(selectinload(cls.items)),
            include_inactive=include_inactive,
        )

    @classmethod
    async def get_for_user(cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID, include_inactive=False):
        return (await session.execute(cls._query(user_id, include_inactive=include_inactive).where(cls.id == entity_id))).scalar_one_or_none()

    @classmethod
    async def list_for_user(cls, session: AsyncSession, *, user_id: PyUUID, query: JournalQuery | None = None):
        options = JournalQuery.model_validate(query or {})
        lower, upper = options.utc_bounds()
        timestamp = getattr(cls, cls.TIME_FIELD)
        statement = cls._query(user_id, include_inactive=options.include_inactive)
        if lower is not None:
            statement = statement.where(timestamp >= lower)
        if upper is not None:
            statement = statement.where(timestamp < upper)
        return list((await session.scalars(statement.order_by(timestamp.desc(), cls.id.desc()).offset(options.offset).limit(options.limit))).all())

    @classmethod
    async def create_snapshot(cls, session: AsyncSession, *, user_id: PyUUID, payload):
        data = cls.CREATE_SCHEMA.model_validate(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            return await cls._insert_snapshot(session, user_id=user_id, data=data)

    @classmethod
    async def replace_for_user(cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID, payload, expected_version_id: int):
        values = payload.to_payload() if hasattr(payload, "to_payload") else dict(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            original = (await session.execute(cls._query(user_id, include_inactive=True).where(cls.id == entity_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            if original is None:
                return None
            require_version(original, expected_version_id)
            if not original.is_active:
                raise HTTPException(409, "Snapshot has been replaced or deleted")
            # Omitted timestamps preserve when the activity happened.
            values.setdefault(cls.TIME_FIELD, getattr(original, cls.TIME_FIELD))
            data = cls.CREATE_SCHEMA.model_validate(values)
            replacement = await cls._insert_snapshot(session, user_id=user_id, data=data, replaces_id=original.id)
            original.is_active = False
            await session.flush()
            return replacement

    @classmethod
    async def soft_delete_for_user(cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID, expected_version_id: int):
        async with session.begin_nested():
            await lock_user(session, user_id)
            entity = (await session.execute(cls._query(user_id, include_inactive=True).where(cls.id == entity_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            if entity is None:
                return None
            require_version(entity, expected_version_id)
            if entity.is_active:
                entity.is_active = False
                await session.flush()
            return entity

    @classmethod
    async def _check_entry(cls, session, user_id, entry_id):
        if entry_id is None:
            return
        from models.plans import MealPlan, MealPlanEntry, TrainingPlan, TrainingPlanEntry

        header, entry = (MealPlan, MealPlanEntry) if cls.TIME_FIELD == "consumed_at" else (TrainingPlan, TrainingPlanEntry)
        # A historical schedule may still be used as the source for a late log.
        found = await session.scalar(select(entry.id).join(header).where(entry.id == entry_id, header.user_id == user_id))
        if found is None:
            raise HTTPException(404, "Scheduled activity not found")
        if cls.TIME_FIELD == "started_at" and await session.scalar(select(entry.is_rest).where(entry.id == entry_id)):
            raise HTTPException(422, "A rest entry cannot be the source of a training")


def journal_constraints(prefix):
    return (
        CheckConstraint("name ~ '[^[:space:]]'", name=f"ck_{prefix}_name"),
        CheckConstraint("source IN ('USER', 'LEGACY_IMPORT')", name=f"ck_{prefix}_source"),
        CheckConstraint("detail_status IN ('DETAILED', 'AGGREGATE_ONLY') AND (detail_status != 'AGGREGATE_ONLY' OR source = 'LEGACY_IMPORT')", name=f"ck_{prefix}_details"),
        CheckConstraint("replaces_id IS NULL OR replaces_id <> id", name=f"ck_{prefix}_replacement"),
    )


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
    source_entry_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meal_plan_entries.id", ondelete="SET NULL"), nullable=True)
    nutrition_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    items: Mapped[list["MealItem"]] = relationship(back_populates="meal", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin", order_by="MealItem.position")

    @classmethod
    async def _insert_snapshot(cls, session, *, user_id, data, replaces_id=None):
        await cls._check_entry(session, user_id, data.source_entry_id)
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


class Training(Journal):
    __tablename__ = "trainings"
    __table_args__ = (
        *journal_constraints("trainings"),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_trainings_dates"),
        CheckConstraint("duration_seconds IS NULL OR (duration_seconds > 0 AND duration_seconds < 1000000000)", name="ck_trainings_duration"),
        CheckConstraint("energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)", name="ck_trainings_energy"),
        Index("ix_trainings_user_started", "user_id", "started_at", "id"),
        UniqueConstraint("replaces_id", name="uq_trainings_replaces"),
    )
    TIME_FIELD = "started_at"
    CREATE_SCHEMA = TrainingCreate

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    calories_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trainings.id", ondelete="RESTRICT"), nullable=True)
    source_entry_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plan_entries.id", ondelete="SET NULL"), nullable=True)
    items: Mapped[list["TrainingItem"]] = relationship(back_populates="training", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin", order_by="TrainingItem.position")

    @classmethod
    async def _insert_snapshot(cls, session, *, user_id, data, replaces_id=None):
        await cls._check_entry(session, user_id, data.source_entry_id)
        items = [await build_exercise_item(session, user_id, item) for item in data.items]
        totals = NutritionTotals.model_validate(sum_known(items, ("energy_kcal",)))
        entity = cls(
            **data.model_dump(exclude={"items"}), user_id=user_id, replaces_id=replaces_id,
            energy_kcal=totals.energy_kcal, calories_incomplete=totals.energy_kcal is None,
            items=[TrainingItem(**item, position=position) for position, item in enumerate(items)],
        )
        session.add(entity)
        await session.flush()
        return entity


class TrainingItem(ExerciseActivityMixin, BaseModel):
    __tablename__ = "training_items"
    __table_args__ = (*exercise_item_constraints("training_items"), UniqueConstraint("training_id", "position", name="uq_training_items_position"))
    training_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False)
    training: Mapped[Training] = relationship(back_populates="items")


for _model in (Meal, MealItem, Training, TrainingItem):
    guard_immutable(_model)
