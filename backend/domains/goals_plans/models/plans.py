"""Phiên bản kế hoạch bất biến và lịch tập theo ngày (checklist hoàn thành từng buổi).

Các phương thức có phạm vi chỉ flush, không bao giờ commit: bên gọi giữ quyền sở hữu transaction.
Mọi lệnh ghi vòng đời đều tuần tự hoá trên cùng dòng User như bước xác nhận Goal.
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

from domains.shared.models.activity import ExercisePlanMixin, build_prescription_item, prescription_item_constraints
from domains.shared.models.basemodel import BaseModel, utc_now
from domains.shared.models.domain import guard_immutable, lock_user, require_version
from domains.shared.schemas.enums import GoalStatus
from domains.goals_plans.schemas.plans import PlanCreate, PlanQuery, TrainingPlanCreate


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
        query = super()._user_query(user_id, include_inactive=include_inactive)
        if hasattr(cls, "entries"):
            query = query.options(selectinload(cls.entries).selectinload(cls._entry_model.items))
        return query

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
                result = await session.execute(
                    TrainingPlan._user_query(self.user_id).where(TrainingPlan.plan_id == self.id, TrainingPlan.status == "ACTIVE")
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
        from domains.goals_plans.schemas.plans import PlanEnd

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

    async def _before_deactivate(self, session: AsyncSession) -> None:
        await self._end(session, "DELETED")


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
        from domains.body.models.body_metrics import BodyMetric
        from domains.goals_plans.models.goal import Goal
        from domains.body.schemas.body_metrics import BodyMetricRead
        from domains.goals_plans.schemas.goal import GoalRead
        from domains.identity.schemas.user import UserRead

        user = await lock_user(session, user_id)
        goal = await Goal.get_for_user(session, payload.goal_id, user_id=user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        # Identity map có thể có từ trước một lần chuyển trạng thái Goal đồng thời đã giữ
        # cùng khoá User; luôn đánh giá và chụp dòng đã làm mới.
        await session.refresh(goal)
        if goal.status != GoalStatus.IN_PROGRESS:
            raise HTTPException(status_code=409, detail="Goal has already ended")
        if payload.end_date < utc_now().astimezone(ZoneInfo(payload.timezone)).date():
            raise HTTPException(status_code=422, detail="An active plan cannot already be expired")
        metric = await BodyMetric.get_latest_for_user(session, user_id=user_id, respect_consent=False)
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
        for model in (cls, TrainingPlan):
            result = await session.execute(
                model._user_query(user_id).where(model.status == "ACTIVE")
                .with_for_update().execution_options(populate_existing=True)
            )
            for entity in result.scalars():
                if entity.end_date < now.astimezone(ZoneInfo(entity.timezone)).date():
                    await entity._end(session, "EXPIRED", now=now)
                    count += 1
            # Flush dây chuyền của bản chính trước khi chọn các lịch chi tiết đang hoạt động.
            await session.flush()
        return count

    @classmethod
    async def end_for_goal(cls, session: AsyncSession, *, user_id: PyUUID, goal_id: PyUUID, reason: str):
        """Được gọi bên trong transaction vòng đời của Goal; cũng an toàn khi service gọi trực tiếp."""
        async with session.begin_nested():
            await lock_user(session, user_id)
            result = await session.execute(
                cls._user_query(user_id).where(cls.goal_id == goal_id, cls.status == "ACTIVE")
                .with_for_update().execution_options(populate_existing=True)
            )
            for entity in result.scalars():
                await entity._end(session, reason)
            await session.flush()


class TrainingPlan(PlanLifecycleMixin, BaseModel):
    __tablename__ = "training_plans"
    __table_args__ = _lifecycle_constraints("training_plans", "plan_id")
    plan_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False)
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plans.id", ondelete="SET NULL"), nullable=True)
    entries: Mapped[list[TrainingPlanEntry]] = relationship("TrainingPlanEntry", cascade="all, delete-orphan", passive_deletes=True, order_by="TrainingPlanEntry.position")
    _entry_model: ClassVar[type]

    @classmethod
    async def list_entries_for_user(cls, session, schedule_id, *, user_id, options):
        from domains.shared.schemas.tracking import ScheduleEntryQuery

        options = ScheduleEntryQuery.model_validate(options)
        header = cls.apply_active_scope(
            select(cls.id).where(cls.id == schedule_id, cls.user_id == user_id),
            include_inactive=options.include_inactive,
        )
        if await session.scalar(header) is None:
            raise HTTPException(404, "Schedule not found")
        query = (select(TrainingPlanEntry).where(TrainingPlanEntry.training_plan_id == schedule_id)
                 .options(selectinload(TrainingPlanEntry.items)))
        lower, upper = options.on_date or options.start_date, options.on_date or options.end_date
        if lower is not None:
            query = query.where(TrainingPlanEntry.scheduled_date >= lower)
        if upper is not None:
            query = query.where(TrainingPlanEntry.scheduled_date <= upper)
        query = query.order_by(TrainingPlanEntry.scheduled_date, TrainingPlanEntry.scheduled_time.nulls_last(),
                               TrainingPlanEntry.position, TrainingPlanEntry.id)
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
    async def _build(cls, session: AsyncSession, *, user_id: PyUUID, parent: Plan, payload, replaces_id: PyUUID | None = None,
                     completed: Mapping[tuple[date, str], datetime] | None = None):
        entries = []
        for position, entry_input in enumerate(payload.entries):
            items = [TrainingPlanItem(**await build_prescription_item(session, user_id, item), position=item_position)
                     for item_position, item in enumerate(entry_input.items)]
            values = entry_input.model_dump(mode="python", exclude={"items"})
            # Bản thay thế giữ dấu hoàn thành của buổi cùng ngày, cùng tên.
            done = None if entry_input.is_rest else (completed or {}).get((entry_input.scheduled_date, entry_input.label))
            entries.append(TrainingPlanEntry(**values, position=position, items=items, completed_at=done))
        entity = cls(
            **payload.model_dump(mode="python", exclude={"entries"}), user_id=user_id, plan_id=parent.id,
            timezone=parent.timezone, replaces_id=replaces_id, entries=entries,
        )
        session.add(entity)
        await session.flush()
        return entity

    @classmethod
    async def create_for_user(cls, session: AsyncSession, *, user_id: PyUUID, plan_id: PyUUID, payload):
        payload = TrainingPlanCreate.model_validate(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            await Plan._expire_locked(session, user_id=user_id)
            parent = await cls._parent(session, user_id=user_id, plan_id=plan_id, payload=payload)
            await cls._require_no_current(session, user_id=user_id, plan_id=plan_id)
            return await cls._build(session, user_id=user_id, parent=parent, payload=payload)

    @classmethod
    async def create_with_parent(cls, session: AsyncSession, *, user_id: PyUUID, payload):
        """Một lệnh xác nhận: dùng kế hoạch cha đang hoạt động, hoặc tạo/nới nó theo mục tiêu hiện tại."""
        from domains.goals_plans.models.goal import Goal

        payload = TrainingPlanCreate.model_validate(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            await Plan._expire_locked(session, user_id=user_id)
            parent = (await session.execute(Plan._user_query(user_id).where(Plan.status == "ACTIVE")
                                            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            if parent is not None:
                await cls._require_no_current(session, user_id=user_id, plan_id=parent.id)
                if parent.start_date <= payload.start_date and payload.end_date <= parent.end_date:
                    return await cls._build(session, user_id=user_id, parent=parent, payload=payload)
            goal = await Goal.get_current_for_user(session, user_id=user_id)
            if goal is None:
                raise HTTPException(409, "Cần đặt một mục tiêu đang thực hiện trước khi lưu lịch tập")
            span = PlanCreate(
                goal_id=goal.id, name=payload.name, note=payload.note, source={"type": "TRAINING_PLAN"},
                start_date=min(payload.start_date, parent.start_date) if parent else payload.start_date,
                end_date=max(payload.end_date, parent.end_date) if parent else payload.end_date,
                **({"timezone": parent.timezone} if parent else {}),
            )
            if parent is not None:
                # Kế hoạch cha bất biến: nới khoảng ngày bằng một phiên bản mới (chưa có lịch tập nào đang chạy).
                await parent._end(session, "REPLACED")
                await session.flush()
            parent = await Plan._build(session, user_id=user_id, payload=span, replaces_id=parent.id if parent else None)
            return await cls._build(session, user_id=user_id, parent=parent, payload=payload)

    @classmethod
    async def _require_no_current(cls, session: AsyncSession, *, user_id: PyUUID, plan_id: PyUUID):
        current = await session.scalar(select(cls.id).where(cls.user_id == user_id, cls.plan_id == plan_id, cls.is_active.is_(True), cls.status == "ACTIVE"))
        if current is not None:
            raise HTTPException(status_code=409, detail="Plan already has an active training schedule; replace it instead")

    @classmethod
    async def replace_for_user(cls, session: AsyncSession, schedule_id: PyUUID, *, user_id: PyUUID, payload, expected_version_id: int):
        payload = TrainingPlanCreate.model_validate(payload.to_payload() if hasattr(payload, "to_payload") else payload)
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
            completed = {(entry.scheduled_date, entry.label): entry.completed_at for entry in original.entries if entry.completed_at}
            await original._end(session, "REPLACED")
            await session.flush()
            return await cls._build(session, user_id=user_id, parent=parent, payload=payload,
                                    replaces_id=original.id, completed=completed)

    @classmethod
    async def previous_for_user(cls, session: AsyncSession, *, user_id: PyUUID):
        """Lịch đã kết thúc gần nhất (kết thúc sớm, hết hạn, theo mục tiêu); phiên bản bị thay thế không tính."""
        query = (cls._user_query(user_id).where(cls.status == "ENDED", cls.end_reason != "REPLACED")
                 .order_by(cls.ended_at.desc(), cls.id.desc()).limit(1))
        return (await session.execute(query)).scalar_one_or_none()

    @classmethod
    async def lock_entry_for_completion(cls, session: AsyncSession, schedule_id: PyUUID, entry_id: PyUUID, *, user_id: PyUUID):
        """Khoá buổi cần tick. Chỉ buổi tập của HÔM NAY được tick; buổi đã qua bị khoá, buổi đã tick không hoàn tác.

        Bên gọi giữ khoá User tới hết transaction (ghi buổi tập thật rồi đặt completed_at)."""
        await lock_user(session, user_id)
        schedule = await cls._locked(session, schedule_id, user_id=user_id)
        if schedule is None:
            return None, None
        entry = next((item for item in schedule.entries if item.id == entry_id), None)
        if entry is None:
            return schedule, None
        if entry.completed_at is not None:
            return schedule, entry
        if schedule.status != "ACTIVE":
            raise HTTPException(409, "Lịch tập đã kết thúc")
        if entry.is_rest:
            raise HTTPException(422, "Buổi nghỉ không cần đánh dấu hoàn thành")
        today = utc_now().astimezone(ZoneInfo(schedule.timezone)).date()
        if entry.scheduled_date < today:
            raise HTTPException(409, "Buổi tập đã quá hạn, không thể đánh dấu hoàn thành")
        if entry.scheduled_date > today:
            raise HTTPException(422, "Chưa tới ngày của buổi tập này")
        return schedule, entry


class TrainingPlanEntry(BaseModel):
    __tablename__ = "training_plan_entries"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_training_plan_entries_position"),
        CheckConstraint("label ~ '[^[:space:]]'", name="ck_training_plan_entries_label"),
        Index("uq_training_plan_entries_position", "training_plan_id", "position", unique=True),
        Index("ix_training_plan_entries_date", "training_plan_id", "scheduled_date"),
    )
    training_plan_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_rest: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[TrainingPlanItem]] = relationship("TrainingPlanItem", cascade="all, delete-orphan", passive_deletes=True, order_by="TrainingPlanItem.position")


class TrainingPlanItem(ExercisePlanMixin, BaseModel):
    __tablename__ = "training_plan_items"
    __table_args__ = (*prescription_item_constraints("training_plan_items"), Index("uq_training_plan_items_position", "entry_id", "position", unique=True))
    entry_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plan_entries.id", ondelete="CASCADE"), nullable=False)


TrainingPlan._entry_model = TrainingPlanEntry
for _model in (Plan, TrainingPlan):
    guard_immutable(_model, allowed={"status", "ended_at", "end_reason"})
guard_immutable(TrainingPlanEntry, allowed={"completed_at"})
guard_immutable(TrainingPlanItem)
