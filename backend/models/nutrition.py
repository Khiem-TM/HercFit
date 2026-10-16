"""SQLAlchemy 2.0 ORM models for Nutrition and Meals."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Meal(Base):
    __tablename__ = "meals"
    __table_args__ = (
        Index("idx_meals_user_logged", "user_id", "logged_at"),
    )

    meal_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    calories: Mapped[int] = mapped_column(Integer, nullable=False)
    protein_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    carbs_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    fat_g: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

