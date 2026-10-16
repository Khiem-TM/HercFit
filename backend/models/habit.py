"""SQLAlchemy 2.0 ORM models for Habits and Daily Check-ins."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Habit(Base):
    __tablename__ = "habits"
    __table_args__ = (
        Index("idx_habits_user", "user_id"),
    )

    habit_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    checkins: Mapped[list["HabitCheckIn"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )


class HabitCheckIn(Base):
    __tablename__ = "habit_checkins"
    __table_args__ = (
        UniqueConstraint("habit_id", "checkin_date", name="uq_habit_checkin_date"),
        Index("idx_habit_checkins_user_date", "user_id", "checkin_date"),
    )

    checkin_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid4())
    )
    habit_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("habits.habit_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    checkin_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )

    habit: Mapped["Habit"] = relationship(back_populates="checkins")

