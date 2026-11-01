"""Hydration and nutrition logs (migration 0020): HercFit-owned or imported from Google Health.

A Google nutrition-log entry is not a HercFit meal: it is kept as its own log and
may be linked to a meal or a catalog food when the identity is certain, so the
same intake is never counted twice.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from domains.shared.models.basemodel import BaseModel

LOG_SOURCES = ("MANUAL", "AI_CONFIRMED", "GOOGLE_HEALTH")



class _ImportableLog:
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", server_default="MANUAL", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(300))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh", server_default="Asia/Ho_Chi_Minh",
                                          nullable=False)
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    # Provenance of an imported row (migration 0023): the provider record it was projected from.
    source_record_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("health_source_records.id", ondelete="SET NULL"), nullable=True)


class HydrationLog(_ImportableLog, BaseModel):
    __tablename__ = "hydration_logs"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'AI_CONFIRMED', 'GOOGLE_HEALTH')", name="ck_hydration_logs_source"),
        CheckConstraint("amount_ml > 0 AND amount_ml <= 10000", name="ck_hydration_logs_amount"),
        Index("ix_hydration_logs_user_time", "user_id", "consumed_at"),
        Index("uq_hydration_logs_external", "user_id", "source", "external_id", unique=True,
              postgresql_where=text("external_id IS NOT NULL")),
    )
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_ml: Mapped[Decimal] = mapped_column(Numeric(8, 1), nullable=False)
    user_unit: Mapped[str | None] = mapped_column(String(30))


class NutritionLog(_ImportableLog, BaseModel):
    __tablename__ = "nutrition_logs"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'AI_CONFIRMED', 'GOOGLE_HEALTH')", name="ck_nutrition_logs_source"),
        Index("ix_nutrition_logs_user_time", "user_id", "consumed_at"),
        Index("uq_nutrition_logs_external", "user_id", "source", "external_id", unique=True,
              postgresql_where=text("external_id IS NOT NULL")),
    )
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meal_type: Mapped[str | None] = mapped_column(String(20))
    food_name: Mapped[str | None] = mapped_column(String(255))
    meal_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meals.id", ondelete="SET NULL"))
    food_id: Mapped[PyUUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"))
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    nutrients: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), default=dict,
                                                      server_default=text("'{}'::jsonb"), nullable=False)
    serving: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), default=dict,
                                                    server_default=text("'{}'::jsonb"), nullable=False)
