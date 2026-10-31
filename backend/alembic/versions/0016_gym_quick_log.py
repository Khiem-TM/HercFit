"""Gym quick log: a system catalog record for a gym session logged by intensity only.

When the user only wants calories for "tập gym" and not every exercise, sets and
load, the session is logged as one SPORT item of this record with its duration and
intensity. Energy comes from services.training_metrics.RESISTANCE_MET (2024 Adult
Compendium 02054 / 02061 / 02050), chosen by the sport "resistance_training".
"""
import json
import unicodedata

from alembic import op
from sqlalchemy import text

revision = "0016_gym_quick_log"
down_revision = "0015_knowledge_retrieval"
branch_labels = depends_on = None

EXERCISE_ID = "54bf874e-3aa7-5d0e-b480-583b7e62ba61"  # uuid5(URL, "hercfit:exercise:SPORT:gym_general")
CODE = "gym_general"
NAME_VI = "Tập gym (tổng quát)"
NAME_EN = "Gym session (general)"
INSTRUCTIONS = "Ghi nhanh buổi tập tạ/thể hình theo thời lượng và cường độ (nhẹ, vừa, mạnh) khi không nhập từng bài."
ALIASES = ("gym", "tap gym", "tap ta", "the hinh", "weight training", "gym session")
CONFIGURATION = {
    "kind": "SPORT", "sport": "resistance_training",
    "met_source": "2024 Adult Compendium: 02054 (3.5), 02061 (5.0), 02050 (6.0) by intensity",
}


def normalize(value):
    # Frozen copy of models.catalog.normalize_food_text, so later app changes cannot alter this migration.
    value = unicodedata.normalize("NFD", (value or "").lower().replace("đ", "d"))
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def upgrade():
    bind = op.get_bind()
    bind.execute(text("""
        INSERT INTO exercises (id, code, name_vi, name_en, kind, source_type, instructions, equipment, muscle_groups,
                               configuration, normalized_name_vi, normalized_name_en, normalized_search_text)
        VALUES (:id, :code, :name_vi, :name_en, 'SPORT', 'SYSTEM', :instructions, '[]'::jsonb, '[]'::jsonb,
                CAST(:configuration AS jsonb), :normalized_vi, :normalized_en, :search)
        ON CONFLICT (kind, code) WHERE source_type = 'SYSTEM' DO NOTHING
    """), {
        "id": EXERCISE_ID, "code": CODE, "name_vi": NAME_VI, "name_en": NAME_EN, "instructions": INSTRUCTIONS,
        "configuration": json.dumps(CONFIGURATION), "normalized_vi": normalize(NAME_VI), "normalized_en": normalize(NAME_EN),
        "search": normalize(" ".join([CODE, NAME_VI, NAME_EN, INSTRUCTIONS, *ALIASES])),
    })
    for alias in ALIASES:
        bind.execute(text("""
            INSERT INTO exercises_aliases (entity_id, normalized_alias)
            SELECT id, :alias FROM exercises WHERE kind = 'SPORT' AND code = :code AND source_type = 'SYSTEM'
            ON CONFLICT DO NOTHING
        """), {"alias": alias, "code": CODE})


def downgrade():
    # Logged sessions keep their record; it is only removed while nothing references it.
    op.execute(text(f"""
        DELETE FROM exercises e WHERE e.id = '{EXERCISE_ID}'
          AND NOT EXISTS (SELECT 1 FROM training_items i WHERE i.exercise_id = e.id)
          AND NOT EXISTS (SELECT 1 FROM training_plan_items p WHERE p.exercise_id = e.id)
    """))
