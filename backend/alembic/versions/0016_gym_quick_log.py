"""Ghi nhanh buổi gym: một bản ghi catalog hệ thống cho buổi gym chỉ ghi theo cường độ.

Khi người dùng chỉ cần calo cho "tập gym" chứ không cần từng bài, set và
mức tạ, buổi tập được ghi thành một mục SPORT của bản ghi này kèm thời lượng và
cường độ. Năng lượng lấy từ domains.training.services.training_metrics.RESISTANCE_MET (2024 Adult
Compendium 02054 / 02061 / 02050), chọn theo môn thể thao "resistance_training".
"""
import json
import unicodedata

from sqlalchemy import text

from alembic import op

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
    # Bản sao đóng băng của models.catalog.normalize_food_text, để thay đổi sau này của app không làm đổi migration này.
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
    # Các buổi tập đã ghi giữ bản ghi của chúng; nó chỉ bị xoá khi không còn gì tham chiếu tới.
    op.execute(text(f"""
        DELETE FROM exercises e WHERE e.id = '{EXERCISE_ID}'
          AND NOT EXISTS (SELECT 1 FROM training_items i WHERE i.exercise_id = e.id)
          AND NOT EXISTS (SELECT 1 FROM training_plan_items p WHERE p.exercise_id = e.id)
    """))
