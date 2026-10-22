"""Add current journal columns missing from the consolidated initial migration.

Preserve legacy columns and totals. Existing current-schema installations are
unchanged. Plan/schedule schema reconciliation is outside this migration.
"""
from alembic import op
from sqlalchemy import inspect

revision = "0003_agent_journal_compat"
down_revision = "0002_api_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    for table, entry in (("meals", "meal_plan_entries"), ("trainings", "training_plan_entries")):
        columns = {c["name"] for c in inspector.get_columns(table)}
        additions = {
            "timezone": "varchar(100) NOT NULL DEFAULT 'Asia/Ho_Chi_Minh'",
            "note": "text",
            "source": "varchar(20) NOT NULL DEFAULT 'USER'",
            "detail_status": "varchar(20) NOT NULL DEFAULT 'DETAILED'",
            "replaces_id": f"uuid REFERENCES {table}(id) ON DELETE RESTRICT",
            "source_entry_id": f"uuid REFERENCES {entry}(id) ON DELETE SET NULL",
        }
        if table == "meals":
            additions["nutrition_incomplete"] = "boolean NOT NULL DEFAULT true"
        else:
            additions.update(
                duration_seconds="numeric(12,3)",
                energy_kcal="numeric(18,6)",
                calories_incomplete="boolean NOT NULL DEFAULT true",
            )
        for column, sql in additions.items():
            if column not in columns:
                op.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql}")
        if "note" not in columns and "notes" in columns:
            op.execute(f"UPDATE {table} SET note = notes")
        if "source" not in columns:
            item = "meal_items" if table == "meals" else "training_items"
            foreign_key = "meal_id" if table == "meals" else "training_id"
            op.execute(f"""
                UPDATE {table} SET source = 'LEGACY_IMPORT',
                    detail_status = CASE WHEN EXISTS (
                        SELECT 1 FROM {item} WHERE {item}.{foreign_key} = {table}.id
                    ) THEN 'DETAILED' ELSE 'AGGREGATE_ONLY' END
            """)
        if table == "meals":
            if "meal_type" in columns:
                op.execute("ALTER TABLE meals ALTER COLUMN meal_type DROP NOT NULL")
            if "nutrition_incomplete" not in columns:
                op.execute("""UPDATE meals SET nutrition_incomplete =
                    energy_kcal IS NULL OR protein_g IS NULL OR carbohydrate_g IS NULL
                    OR fat_g IS NULL OR fiber_g IS NULL""")
        else:
            if "duration_seconds" not in columns and "duration_minutes" in columns:
                op.execute("UPDATE trainings SET duration_seconds = duration_minutes * 60")
            if "energy_kcal" not in columns and "total_calories_burned" in columns:
                op.execute("UPDATE trainings SET energy_kcal = total_calories_burned")
            if "calories_incomplete" not in columns:
                op.execute("UPDATE trainings SET calories_incomplete = energy_kcal IS NULL")
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_replaces ON {table}(replaces_id)")
    columns = {c["name"] for c in inspector.get_columns("meal_items")}
    if "note" not in columns:
        op.execute("ALTER TABLE meal_items ADD COLUMN note text")
        if "notes" in columns:
            op.execute("UPDATE meal_items SET note = notes")
    if "nutrition_incomplete" not in columns:
        op.execute("ALTER TABLE meal_items ADD COLUMN nutrition_incomplete boolean NOT NULL DEFAULT true")
        op.execute("""UPDATE meal_items SET nutrition_incomplete =
            energy_kcal IS NULL OR protein_g IS NULL OR carbohydrate_g IS NULL
            OR fat_g IS NULL OR fiber_g IS NULL""")


def downgrade():
    # Columns may predate this revision on existing installations; dropping them
    # would destroy user data. Rolling back code can leave additive columns intact.
    pass
