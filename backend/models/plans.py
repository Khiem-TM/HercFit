"""Immutable plan versions and dated meal/training schedules.

Scoped methods flush but never commit: callers retain transaction ownership.
All lifecycle writers serialize on the same User row as Goal confirmation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID as PyUUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Time, select, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from models.activity import (
    ExerciseActivityMixin, FoodPortionMixin, build_exercise_item, build_food_item,
    exercise_item_constraints, food_item_constraints,
)
from models.basemodel import BaseModel, utc_now
from models.domain import guard_immutable, lock_user, require_version
from schemas.common import UserScope
from schemas.enums import GoalStatus
from schemas.plans import MealPlanCreate, PlanCreate, PlanQuery, TrainingPlanCreate


def _lifecycle_constraints(table: str, slot: str):
    return (
        CheckConstraint("end_date >= start_date", name=f"ck_{table}_dates"),
        CheckConstraint("name ~ '[^[:space:]]'", name=f"ck_{table}_name"),
        CheckConstraint("status IN ('ACTIVE', 'ENDED')", name=f"ck_{table}_status"),
        CheckConstraint(
            "(status = 'ACTIVE' AND ended_at IS NULL AND end_reason IS NULL) OR "
            "(status = 'ENDED' AND ended_at IS NOT NULL AND end_reason IS NOT NULL)",
            name=f"ck_{table}_lifecycle",
        ),
        CheckConstraint("is_active OR status = 'ENDED'", name=f"ck_{table}_deleted_ended"),
        Index(f"ix_{table}_user_created", "user_id", "created_at", "id"),
        Index(f"uq_{table}_current", slot, unique=True, postgresql_where=text("is_active = true AND status = 'ACTIVE'")),
    )


class PlanLifecycleMixin:
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="Asia/Ho_Chi_Minh", server_default="Asia/Ho_Chi_Minh", nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", server_default="ACTIVE", nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @classmethod
    def _user_query(cls, user_id: PyUUID, *, include_inactive: bool = False):
        user_id = UserScope(user_id=user_id).user_id
        query = cls.apply_active_scope(select(cls).where(cls.user_id == user_id), include_inactive=include_inactive)
        if hasattr(cls, "entries"):
            query = query.options(selectinload(cls.entries).selectinload(cls._entry_model.items))
        return query

    @classmethod
    async def get_for_user(cls, session: AsyncSession, plan_id: PyUUID, *, user_id: PyUUID, include_inactive: bool = False):
        result = await session.execute(cls._user_query(user_id, include_inactive=include_inactive).where(cls.id == plan_id))
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls, session: AsyncSession, *, user_id: PyUUID, offset: int = 0, limit: int = 50,
        include_inactive: bool = False, status: str | None = None,
        goal_id: PyUUID | None = None, plan_id: PyUUID | None = None,
    ):
        options = PlanQuery(offset=offset, limit=limit, include_inactive=include_inactive, status=status, goal_id=goal_id, plan_id=plan_id)
        query = cls._user_query(user_id, include_inactive=options.include_inactive)
        if options.status is not None:
            query = query.where(cls.status == options.status)
        if goal_id is not None:
            if not hasattr(cls, "goal_id"):
                query = query.join(Plan, cls.plan_id == Plan.id).where(Plan.goal_id == goal_id)
            else:
                query = query.where(cls.goal_id == goal_id)
        if plan_id is not None:
            query = query.where(cls.id == plan_id) if cls is Plan else query.where(cls.plan_id == plan_id)
        result = await session.execute(query.order_by(cls.created_at.desc(), cls.id.desc()).offset(options.offset).limit(options.limit))
        return list(result.scalars().all())

    @classmethod
    async def get_current_for_user(cls, session: AsyncSession, *, user_id: PyUUID, plan_id: PyUUID | None = None):
        async with session.begin_nested():
            await lock_user(session, user_id)
            await Plan._expire_locked(session, user_id=user_id)
            query = cls._user_query(user_id).where(cls.status == "ACTIVE")
            if cls is not Plan and plan_id is not None:
                query = query.where(cls.plan_id == plan_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    @classmethod
    async def _locked(cls, session: AsyncSession, plan_id: PyUUID, *, user_id: PyUUID, include_inactive: bool = False):
        result = await session.execute(
            cls._user_query(user_id, include_inactive=include_inactive).where(cls.id == plan_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def _end(self, session: AsyncSession, reason: str, *, now: datetime | None = None):
        if self.status == "ACTIVE":
            if isinstance(self, Plan):
                for model in (MealPlan, TrainingPlan):
                    result = await session.execute(
                        model._user_query(self.user_id).where(model.plan_id == self.id, model.status == "ACTIVE")
                        .with_for_update().execution_options(populate_existing=True)
                    )
                    for child in result.scalars():
                        await child._end(session, reason, now=now)
            self.status = "ENDED"
            self.ended_at = now or utc_now()
            self.end_reason = reason

    @classmethod
    async def end_for_user(
        cls, session: AsyncSession, plan_id: PyUUID, *, user_id: PyUUID,
        expected_version_id: int, reason: str = "USER_ENDED",
    ):
        from schemas.plans import PlanEnd

        validated = PlanEnd(expected_version_id=expected_version_id, reason=reason)
        async with session.begin_nested():
            await lock_user(session, user_id)
            entity = await cls._locked(session, plan_id, user_id=user_id)
            if entity is None:
                return None
            require_version(entity, validated.expected_version_id)
            await entity._end(session, validated.reason)
            await session.flush()
        return entity

    @classmethod
    async def soft_delete_for_user(
        cls, session: AsyncSession, plan_id: PyUUID, *, user_id: PyUUID, expected_version_id: int,
    ):
        async with session.begin_nested():
            await lock_user(session, user_id)
            entity = await cls._locked(session, plan_id, user_id=user_id, include_inactive=True)
            if entity is None:
                return None
            require_version(entity, expected_version_id)
            await entity._end(session, "DELETED")
            entity.is_active = False
            await session.flush()
        return entity


class Plan(PlanLifecycleMixin, BaseModel):
    __tablename__ = "plans"
    __table_args__ = (
        *_lifecycle_constraints("plans", "user_id"),
        *[CheckConstraint(f"{field} >= 0 AND {field} < 1000000000", name=f"ck_plans_{field}") for field in (
            "calories_in_kcal", "calories_out_kcal", "exercise_calories_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g",
        )],
        *[CheckConstraint(f"jsonb_typeof({field}) = 'object'", name=f"ck_plans_{field}") for field in (
            "extra_metrics", "source", "profile_snapshot", "body_metric_snapshot", "goal_snapshot",
        )],
        Index("ix_plans_goal", "goal_id"),
    )
    goal_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("goals.id", ondelete="RESTRICT"), nullable=False)
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    calories_in_kcal: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    calories_out_kcal: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    exercise_calories_kcal: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    extra_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    body_metric_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    goal_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)

    @classmethod
    async def _build(cls, session: AsyncSession, *, user_id: PyUUID, payload: PlanCreate, replaces_id: PyUUID | None = None):
        from models.body_metrics import BodyMetric
        from models.goal import Goal
        from schemas.body_metrics import BodyMetricRead
        from schemas.goal import GoalRead
        from schemas.user import UserRead

        user = await lock_user(session, user_id)
        goal = await Goal.get_for_user(session, payload.goal_id, user_id=user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        # The identity map may predate a concurrent Goal transition that held
        # the same User lock; always evaluate and snapshot the refreshed row.
        await session.refresh(goal)
        if goal.status != GoalStatus.IN_PROGRESS:
            raise HTTPException(status_code=409, detail="Goal has already ended")
        if payload.end_date < utc_now().astimezone(ZoneInfo(payload.timezone)).date():
            raise HTTPException(status_code=422, detail="An active plan cannot already be expired")
        metric = await BodyMetric.get_latest_for_user(session, user_id=user_id)
        values = payload.model_dump(mode="python", exclude={"extra_metrics", "source"})
        entity = cls(
            **values, user_id=user_id, replaces_id=replaces_id,
            extra_metrics=payload.model_dump(mode="json")["extra_metrics"], source=payload.source,
            profile_snapshot=UserRead.model_validate(user).model_dump(mode="json"),
            body_metric_snapshot=BodyMetricRead.model_validate(metric).model_dump(mode="json") if metric else None,
            goal_snapshot=GoalRead.model_validate(goal).model_dump(mode="json"),
        )
        session.add(entity)
        await session.flush()
        return entity

    @classmethod
    async def create_for_user(cls, session: AsyncSession, *, user_id: PyUUID, payload: PlanCreate | Mapping[str, Any]):
        payload = PlanCreate.model_validate(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            await cls._expire_locked(session, user_id=user_id)
            current = await session.scalar(select(cls.id).where(cls.user_id == user_id, cls.is_active.is_(True), cls.status == "ACTIVE"))
            if current is not None:
                raise HTTPException(status_code=409, detail="User already has an active plan; use versioned replacement")
            return await cls._build(session, user_id=user_id, payload=payload)

    @classmethod
    async def replace_for_user(
        cls, session: AsyncSession, plan_id: PyUUID, *, user_id: PyUUID,
        payload: PlanCreate | Mapping[str, Any], expected_version_id: int,
    ):
        payload = PlanCreate.model_validate(payload.to_payload() if hasattr(payload, "to_payload") else payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            await cls._expire_locked(session, user_id=user_id)
            original = await cls._locked(session, plan_id, user_id=user_id)
            if original is None:
                return None
            require_version(original, expected_version_id)
            if original.status != "ACTIVE":
                raise HTTPException(status_code=409, detail="Plan has already ended")
            await original._end(session, "REPLACED")
            await session.flush()
            return await cls._build(session, user_id=user_id, payload=payload, replaces_id=original.id)

    @classmethod
    async def _expire_locked(cls, session: AsyncSession, *, user_id: PyUUID, now: datetime | None = None):
        now = now or utc_now()
        count = 0
        for model in (cls, MealPlan, TrainingPlan):
            result = await session.execute(
                model._user_query(user_id).where(model.status == "ACTIVE")
                .with_for_update().execution_options(populate_existing=True)
            )
            for entity in result.scalars():
                if entity.end_date < now.astimezone(ZoneInfo(entity.timezone)).date():
                    await entity._end(session, "EXPIRED", now=now)
                    count += 1
            # Flush the master cascade before selecting active detail schedules.
            await session.flush()
        return count

    @classmethod
    async def expire_for_user(cls, session: AsyncSession, *, user_id: PyUUID, now: datetime | None = None):
        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError("now must be timezone-aware")
        async with session.begin_nested():
            await lock_user(session, user_id)
            return await cls._expire_locked(session, user_id=user_id, now=now)

    @classmethod
    async def end_for_goal(cls, session: AsyncSession, *, user_id: PyUUID, goal_id: PyUUID, reason: str):
        """Called inside Goal lifecycle transactions; safe for direct service use too."""
        async with session.begin_nested():
            await lock_user(session, user_id)
            result = await session.execute(
                cls._user_query(user_id).where(cls.goal_id == goal_id, cls.status == "ACTIVE")
                .with_for_update().execution_options(populate_existing=True)
            )
            for entity in result.scalars():
                await entity._end(session, reason)
            await session.flush()


class DetailedPlanMixin(PlanLifecycleMixin):
    plan_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    _create_schema: ClassVar[type]
    _entry_model: ClassVar[type]
    _item_model: ClassVar[type]
    _item_builder: ClassVar[Any]

    @classmethod
    async def list_entries_for_user(cls, session, schedule_id, *, user_id, options):
        from schemas.tracking import ScheduleEntryQuery

        options = ScheduleEntryQuery.model_validate(options)
        header = cls.apply_active_scope(
            select(cls.id).where(cls.id == schedule_id, cls.user_id == user_id),
            include_inactive=options.include_inactive,
        )
        if await session.scalar(header) is None:
            raise HTTPException(404, "Schedule not found")
        entry = cls._entry_model
        parent_key = getattr(entry, f"{cls.__tablename__[:-1]}_id")
        query = select(entry).where(parent_key == schedule_id).options(selectinload(entry.items))
        lower, upper = options.on_date or options.start_date, options.on_date or options.end_date
        if lower is not None:
            query = query.where(entry.scheduled_date >= lower)
        if upper is not None:
            query = query.where(entry.scheduled_date <= upper)
        query = query.order_by(entry.scheduled_date, entry.scheduled_time.nulls_last(), entry.position, entry.id)
        return list((await session.scalars(query.offset(options.offset).limit(options.limit))).all())

    @classmethod
    async def _parent(cls, session: AsyncSession, *, user_id: PyUUID, plan_id: PyUUID, payload):
        parent = await Plan._locked(session, plan_id, user_id=user_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Plan not found")
        if parent.status != "ACTIVE":
            raise HTTPException(status_code=409, detail="Parent plan has already ended")
        if payload.start_date < parent.start_date or payload.end_date > parent.end_date:
            raise HTTPException(status_code=422, detail="Schedule dates must fall within the parent plan")
        if payload.end_date < utc_now().astimezone(ZoneInfo(parent.timezone)).date():
            raise HTTPException(status_code=422, detail="An active schedule cannot already be expired")
        return parent

    @classmethod
    async def _build(cls, session: AsyncSession, *, user_id: PyUUID, parent: Plan, payload, replaces_id: PyUUID | None = None):
        entries = []
        for position, entry_input in enumerate(payload.entries):
            items = []
            for item_position, item_input in enumerate(entry_input.items):
                values = await cls._item_builder(session, user_id, item_input)
                items.append(cls._item_model(**values, position=item_position))
            entries.append(cls._entry_model(**entry_input.model_dump(mode="python", exclude={"items"}), position=position, items=items))
        entity = cls(
            **payload.model_dump(mode="python", exclude={"entries"}), user_id=user_id, plan_id=parent.id,
            timezone=parent.timezone, replaces_id=replaces_id, entries=entries,
        )
        session.add(entity)
        await session.flush()
        return entity

    @classmethod
    async def create_for_user(cls, session: AsyncSession, *, user_id: PyUUID, plan_id: PyUUID, payload):
        payload = cls._create_schema.model_validate(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            await Plan._expire_locked(session, user_id=user_id)
            parent = await cls._parent(session, user_id=user_id, plan_id=plan_id, payload=payload)
            current = await session.scalar(select(cls.id).where(cls.user_id == user_id, cls.plan_id == plan_id, cls.is_active.is_(True), cls.status == "ACTIVE"))
            if current is not None:
                raise HTTPException(status_code=409, detail="Plan already has an active schedule of this type")
            return await cls._build(session, user_id=user_id, parent=parent, payload=payload)

    @classmethod
    async def replace_for_user(cls, session: AsyncSession, schedule_id: PyUUID, *, user_id: PyUUID, payload, expected_version_id: int):
        payload = cls._create_schema.model_validate(payload.to_payload() if hasattr(payload, "to_payload") else payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            await Plan._expire_locked(session, user_id=user_id)
            original = await cls._locked(session, schedule_id, user_id=user_id)
            if original is None:
                return None
            require_version(original, expected_version_id)
            if original.status != "ACTIVE":
                raise HTTPException(status_code=409, detail="Schedule has already ended")
            parent = await cls._parent(session, user_id=user_id, plan_id=original.plan_id, payload=payload)
            await original._end(session, "REPLACED")
            await session.flush()
            return await cls._build(session, user_id=user_id, parent=parent, payload=payload, replaces_id=original.id)


class MealPlan(DetailedPlanMixin, BaseModel):
    __tablename__ = "meal_plans"
    __table_args__ = _lifecycle_constraints("meal_plans", "plan_id")
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="SET NULL"), nullable=True)
    entries: Mapped[list[MealPlanEntry]] = relationship("MealPlanEntry", cascade="all, delete-orphan", passive_deletes=True, order_by="MealPlanEntry.position")


class TrainingPlan(DetailedPlanMixin, BaseModel):
    __tablename__ = "training_plans"
    __table_args__ = _lifecycle_constraints("training_plans", "plan_id")
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plans.id", ondelete="SET NULL"), nullable=True)
    entries: Mapped[list[TrainingPlanEntry]] = relationship("TrainingPlanEntry", cascade="all, delete-orphan", passive_deletes=True, order_by="TrainingPlanEntry.position")


class ScheduleEntryMixin:
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


def _entry_constraints(table: str, parent_id: str):
    return (
        CheckConstraint("position >= 0", name=f"ck_{table}_position"),
        CheckConstraint("label ~ '[^[:space:]]'", name=f"ck_{table}_label"),
        Index(f"uq_{table}_position", parent_id, "position", unique=True),
        Index(f"ix_{table}_date", parent_id, "scheduled_date"),
    )


class MealPlanEntry(ScheduleEntryMixin, BaseModel):
    __tablename__ = "meal_plan_entries"
    __table_args__ = _entry_constraints("meal_plan_entries", "meal_plan_id")
    meal_plan_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), nullable=False)
    meal_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    items: Mapped[list[MealPlanItem]] = relationship("MealPlanItem", cascade="all, delete-orphan", passive_deletes=True, order_by="MealPlanItem.position")


class TrainingPlanEntry(ScheduleEntryMixin, BaseModel):
    __tablename__ = "training_plan_entries"
    __table_args__ = _entry_constraints("training_plan_entries", "training_plan_id")
    training_plan_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False)
    is_rest: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    items: Mapped[list[TrainingPlanItem]] = relationship("TrainingPlanItem", cascade="all, delete-orphan", passive_deletes=True, order_by="TrainingPlanItem.position")


class MealPlanItem(FoodPortionMixin, BaseModel):
    __tablename__ = "meal_plan_items"
    __table_args__ = (*food_item_constraints("meal_plan_items"), Index("uq_meal_plan_items_position", "entry_id", "position", unique=True))
    entry_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meal_plan_entries.id", ondelete="CASCADE"), nullable=False)


class TrainingPlanItem(ExerciseActivityMixin, BaseModel):
    __tablename__ = "training_plan_items"
    __table_args__ = (*exercise_item_constraints("training_plan_items"), Index("uq_training_plan_items_position", "entry_id", "position", unique=True))
    entry_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plan_entries.id", ondelete="CASCADE"), nullable=False)


MealPlan._create_schema, MealPlan._entry_model, MealPlan._item_model = MealPlanCreate, MealPlanEntry, MealPlanItem
TrainingPlan._create_schema, TrainingPlan._entry_model, TrainingPlan._item_model = TrainingPlanCreate, TrainingPlanEntry, TrainingPlanItem
MealPlan._item_builder = staticmethod(build_food_item)
TrainingPlan._item_builder = staticmethod(build_exercise_item)
for _model in (Plan, MealPlan, TrainingPlan):
    guard_immutable(_model, allowed={"status", "ended_at", "end_reason"})
for _model in (MealPlanEntry, TrainingPlanEntry, MealPlanItem, TrainingPlanItem):
    guard_immutable(_model)
