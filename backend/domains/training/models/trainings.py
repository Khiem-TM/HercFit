"""Aggregate hoạt động thực tế bất biến với sửa nguyên tử và lệnh đọc có phạm vi.

Tách ra từ models.journals trong đợt tổ chức lại theo miền."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID as PyUUID
from fastapi import HTTPException
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from domains.shared.models.activity import (
    ExerciseActualMixin,
    build_exercise_item,
    exercise_item_constraints,
    sum_known,
)
from domains.shared.models.basemodel import BaseModel
from domains.shared.models.domain import guard_immutable
from domains.shared.schemas.activity import NutritionTotals
from domains.catalog.schemas.exercises import ExerciseKind
from domains.training.schemas.trainings import GYM_GENERAL_CODE, TrainingCreate
from domains.training.services.training_metrics import allocate_session_time, session_load
from domains.shared.models.journal import Journal, journal_constraints


class Training(Journal):
    __tablename__ = "trainings"
    __table_args__ = (
        *journal_constraints("trainings"),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_trainings_dates"),
        CheckConstraint("duration_seconds IS NULL OR (duration_seconds > 0 AND duration_seconds < 1000000000)", name="ck_trainings_duration"),
        CheckConstraint("energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)", name="ck_trainings_energy"),
        CheckConstraint("discipline IN ('STRENGTH', 'ENDURANCE', 'SPORT', 'MIXED')", name="ck_trainings_discipline"),
        CheckConstraint("session_rpe IS NULL OR (session_rpe >= 0 AND session_rpe <= 10)", name="ck_trainings_session_rpe"),
        CheckConstraint("training_load IS NULL OR training_load >= 0", name="ck_trainings_load"),
        Index("ix_trainings_user_started", "user_id", "started_at", "id"),
        Index("ix_trainings_user_discipline", "user_id", "discipline", "started_at"),
        UniqueConstraint("replaces_id", name="uq_trainings_replaces"),
    )
    TIME_FIELD = "started_at"
    CREATE_SCHEMA = TrainingCreate

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    calories_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discipline: Mapped[str] = mapped_column(String(10), nullable=False)
    session_rpe: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    training_load: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    replaces_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trainings.id", ondelete="RESTRICT"), nullable=True)
    source_entry_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("training_plan_entries.id", ondelete="SET NULL"), nullable=True)
    items: Mapped[list["TrainingItem"]] = relationship(back_populates="training", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin", order_by="TrainingItem.position")

    @classmethod
    async def _insert_snapshot(cls, session, *, user_id, data, replaces_id=None):
        from domains.body.models.body_metrics import BodyMetric

        await cls._check_entry(session, user_id, data.source_entry_id)
        latest = await BodyMetric.get_latest_for_user(session, user_id=user_id, respect_consent=False)
        bodyweight = float(latest.weight_kg) if latest is not None and latest.weight_kg is not None else None
        items = [await build_exercise_item(session, user_id, item, bodyweight_kg=bodyweight) for item in data.items]
        if any(item["kind"] != ExerciseKind.STRENGTH and item["exercise_snapshot"].get("code") != GYM_GENERAL_CODE
               for item in items):
            raise HTTPException(422, "Nhật ký tập chỉ gồm buổi gym; buổi thể thao ghi bằng log_sport_session "
                                     "(lưu trên Google Health).")
        allocate_session_time(items, float(data.duration_seconds) if data.duration_seconds else None)
        for item in items:
            kcal = item["calorie_estimate"].get("kcal")
            item["energy_kcal"] = None if kcal is None else Decimal(str(kcal))
            if item["duration_seconds"] is not None:
                item["duration_seconds"] = Decimal(str(item["duration_seconds"]))
        totals = NutritionTotals.model_validate(sum_known(items, ("energy_kcal",)))
        kinds = {item["kind"] for item in items}
        # sRPE dùng cả buổi tập (kể cả thời gian chuyển); nếu không có thì dùng tổng thời gian các mục.
        duration = data.duration_seconds or sum((item["duration_seconds"] or Decimal(0) for item in items), Decimal(0)) or None
        entity = cls(
            **data.model_dump(exclude={"items"}), user_id=user_id, replaces_id=replaces_id,
            energy_kcal=totals.energy_kcal, calories_incomplete=totals.energy_kcal is None,
            discipline=kinds.pop().value if len(kinds) == 1 else "MIXED",
            training_load=session_load(data.session_rpe, float(duration) if duration else None),
            items=[TrainingItem(**item, position=position) for position, item in enumerate(items)],
        )
        session.add(entity)
        await session.flush()
        return entity

class TrainingItem(ExerciseActualMixin, BaseModel):
    __tablename__ = "training_items"
    __table_args__ = (
        *exercise_item_constraints("training_items"), UniqueConstraint("training_id", "position", name="uq_training_items_position"),
        Index("ix_training_items_exercise", "exercise_id"),
    )
    training_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trainings.id", ondelete="CASCADE"), nullable=False)
    training: Mapped[Training] = relationship(back_populates="items")


guard_immutable(Training, allowed=("image_url", "image_public_id"))
guard_immutable(TrainingItem, allowed=())
