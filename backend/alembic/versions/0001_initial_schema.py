"""Initial schema for Users, Body Metrics, Nutrition, Workouts, and Habits.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-16 23:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("fitness_goal", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "body_metrics",
        sa.Column("metric_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("muscle_mass_kg", sa.Float(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("metric_id"),
    )
    op.create_index(
        "idx_body_metrics_user_recorded",
        "body_metrics",
        ["user_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "meals",
        sa.Column("meal_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("calories", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Float(), server_default="0", nullable=False),
        sa.Column("carbs_g", sa.Float(), server_default="0", nullable=False),
        sa.Column("fat_g", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("meal_id"),
    )
    op.create_index(
        "idx_meals_user_logged", "meals", ["user_id", "logged_at"], unique=False
    )

    op.create_table(
        "workout_plans",
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.Column(
            "exercises",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index(
        "idx_workout_plans_user",
        "workout_plans",
        ["user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "workout_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("workout_name", sa.String(length=255), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("calories_burned", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "idx_workout_sessions_user_performed",
        "workout_sessions",
        ["user_id", "performed_at"],
        unique=False,
    )

    op.create_table(
        "habits",
        sa.Column("habit_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("habit_id"),
    )
    op.create_index("idx_habits_user", "habits", ["user_id"], unique=False)

    op.create_table(
        "habit_checkins",
        sa.Column("checkin_id", sa.String(length=64), nullable=False),
        sa.Column("habit_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column(
            "checkin_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.habit_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("checkin_id"),
        sa.UniqueConstraint("habit_id", "checkin_date", name="uq_habit_checkin_date"),
    )
    op.create_index(
        "idx_habit_checkins_user_date",
        "habit_checkins",
        ["user_id", "checkin_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_habit_checkins_user_date", table_name="habit_checkins")
    op.drop_table("habit_checkins")
    op.drop_index("idx_habits_user", table_name="habits")
    op.drop_table("habits")
    op.drop_index("idx_workout_sessions_user_performed", table_name="workout_sessions")
    op.drop_table("workout_sessions")
    op.drop_index("idx_workout_plans_user", table_name="workout_plans")
    op.drop_table("workout_plans")
    op.drop_index("idx_meals_user_logged", table_name="meals")
    op.drop_table("meals")
    op.drop_index("idx_body_metrics_user_recorded", table_name="body_metrics")
    op.drop_table("body_metrics")
    op.drop_table("users")

