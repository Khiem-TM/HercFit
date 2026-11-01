"""Symptom, mood, menstrual period and ovulation test logs (migration 0020).

Google Health accepts these only as writes (no read scope in the guide), so
HercFit is the system of record: history cannot be imported, only exported.
They are sensitive: never projected into the knowledge graph, and the assistant
needs the separate `sensitive` consent to read them.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from domains.shared.models.basemodel import BaseModel

SOURCES = ("MANUAL", "AI_CONFIRMED")
# Enumerations pinned to the discovery snapshot (tests/test_google_health_contract.py checks them).
SYMPTOMS = ('CRAMPS', 'HEADACHE', 'TENDER_BREASTS', 'ACNE', 'SICK', 'BLOATED', 'HOT_FLASHES', 'PMS', 'COUGH', 'FEVER', 'DIFFICULTY_BREATHING', 'BACK_PAIN', 'SHAKINESS', 'HUNGER', 'SWEATING', 'ANXIETY', 'THIRST', 'FREQUENT_URINATION', 'BLURRED_VISION', 'OTHER', 'SEX_DRIVE_HIGH', 'SEX_DRIVE_MEDIUM', 'SEX_DRIVE_LOW', 'HEART_PALPITATIONS', 'FAINTING', 'CHEST_PAIN', 'FATIGUE', 'CONFUSION', 'DIZZINESS', 'ABDOMINAL_PAIN', 'BLADDER_LEAKS', 'BLEEDING_GUMS', 'BRAIN_FOG', 'BURNING_MOUTH', 'CONSTIPATION', 'CRAVINGS', 'DECREASED_APPETITE', 'DIARRHEA', 'DRAWING_PAIN', 'DRY_EYES', 'DRY_HAIR', 'DRY_SKIN', 'EXHAUSTION', 'FEEL_GOOD', 'FOOD_AVERSIONS', 'HAIR_LOSS', 'HEARTBURN', 'HYPERPIGMENTATION', 'INCREASED_APPETITE', 'INCREASED_APPETITE_V2', 'INSOMNIA', 'JOINT_PAIN', 'LEG_CRAMPS', 'MILKY_NIPPLE_DISCHARGE', 'NAUSEA', 'NIGHT_SWEATS', 'NORMAL_DIGESTION', 'NORMAL_STOOL', 'PERINEUM_PAIN', 'SLEEPINESS', 'STRETCH_MARKS', 'SWELLING', 'VAGINAL_DRYNESS', 'VAGINAL_ITCHING', 'VOMITING')
MOODS = ('AMAZED', 'AMUSED', 'ANGRY', 'ANNOYED', 'ANXIOUS', 'HAPPY', 'CONTENT', 'SAD', 'WORRIED', 'FRUSTRATED', 'EXCITED', 'CALM', 'STRESSED', 'ASHAMED', 'BRAVE', 'CONFIDENT', 'DISAPPOINTED', 'DISCOURAGED', 'DISGUSTED', 'DRAINED', 'EMBARRASSED', 'GRATEFUL', 'GUILTY', 'HOPEFUL', 'HOPELESS', 'INDIFFERENT', 'IRRITATED', 'JEALOUS', 'JOYFUL', 'LONELY', 'OVERWHELMED', 'PASSIONATE', 'PEACEFUL', 'PROUD', 'RELIEVED', 'SATISFIED', 'SCARED', 'SURPRISED', 'ENERGIZED', 'FATIGUED', 'VERY_CALM', 'VERY_STRESSED', 'NEUTRAL', 'AFRAID', 'HURTING', 'BORED', 'BITTER', 'ENVIOUS', 'CONFUSED', 'CURIOUS', 'AWESTRUCK', 'INSPIRED', 'LONGING', 'ACCOMPLISHED', 'LOVING', 'COMPASSIONATE', 'DEPRESSED', 'GOOD', 'LOW_ENERGY', 'OBSESSIVE_THOUGHTS', 'PANIC', 'PLAYFUL', 'PLEASED', 'SENSITIVE', 'SLEEPY', 'SWINGS', 'UNHAPPY', 'VERY_SELF_CRITICAL')
VALENCES = ('UNPLEASANT', 'BASELINE', 'PLEASANT')
OVULATION_RESULTS = ('NEGATIVE', 'LUTEINIZING_HORMONE_SURGE', 'ESTROGEN_SURGE', 'POSITIVE', 'INDETERMINATE')
MEAL_TYPES = ('BEFORE_BREAKFAST', 'BREAKFAST', 'BEFORE_LUNCH', 'LUNCH', 'BEFORE_DINNER', 'DINNER', 'AFTER_DINNER', 'SNACK', 'ANYTIME')

class _WellbeingLog:
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", server_default="MANUAL", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(300))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh", server_default="Asia/Ho_Chi_Minh",
                                          nullable=False)
    utc_offset_s: Mapped[int | None] = mapped_column(Integer)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def _json_list():
    return mapped_column(JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False)


class SymptomLog(_WellbeingLog, BaseModel):
    __tablename__ = "symptom_logs"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'AI_CONFIRMED')", name="ck_symptom_logs_source"),
        CheckConstraint("jsonb_typeof(symptoms) = 'array' AND jsonb_array_length(symptoms) > 0",
                        name="ck_symptom_logs_symptoms"),
        Index("ix_symptom_logs_user_time", "user_id", "recorded_at"),
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symptoms: Mapped[list[Any]] = _json_list()


class MoodLog(_WellbeingLog, BaseModel):
    __tablename__ = "mood_logs"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'AI_CONFIRMED')", name="ck_mood_logs_source"),
        CheckConstraint("jsonb_array_length(moods) + jsonb_array_length(valences) > 0", name="ck_mood_logs_content"),
        Index("ix_mood_logs_user_time", "user_id", "recorded_at"),
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    moods: Mapped[list[Any]] = _json_list()
    valences: Mapped[list[Any]] = _json_list()


class MenstrualPeriodLog(_WellbeingLog, BaseModel):
    __tablename__ = "menstrual_period_logs"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'AI_CONFIRMED')", name="ck_menstrual_period_logs_source"),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_menstrual_period_logs_interval"),
        Index("ix_menstrual_period_logs_user_time", "user_id", "started_at"),
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OvulationTestLog(_WellbeingLog, BaseModel):
    __tablename__ = "ovulation_test_logs"
    __table_args__ = (
        CheckConstraint("source IN ('MANUAL', 'AI_CONFIRMED')", name="ck_ovulation_test_logs_source"),
        Index("ix_ovulation_test_logs_user_time", "user_id", "recorded_at"),
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result: Mapped[str] = mapped_column(String(40), nullable=False)
