"""Truy hồi tri thức: tìm kiếm toàn văn có trọng số theo ngôn ngữ và khoảng trang.

* knowledge_document(lang, heading, content) dựng tsvector của chunk: tiêu đề chương
  có trọng số 'A' và đoạn văn 'B'; tài liệu tiếng Anh dùng cấu hình 'english'
  có rút gọn từ (bỏ stop word), các tài liệu khác giữ 'simple'.
* knowledge_query(lang, q) biến một câu hỏi tự nhiên thành phép OR của các
  lexeme. plainto_tsquery AND trước đây đòi mọi từ của câu hỏi nằm trong
  một chunk và gần như không khớp gì.
* knowledge_chunks có thêm page_end (một chunk có thể trải nhiều trang) và page_label (số
  trang in, khi đặc tả nguồn ánh xạ được).

Văn bản được chuẩn hoá trong Python (chữ thường, bỏ dấu) trước khi tới các
hàm này, lúc tiếp nhận và lúc truy vấn, đúng như trước.
"""
import unicodedata

from sqlalchemy import text

from alembic import op

revision = "0015_knowledge_retrieval"
down_revision = "0014_google_health"
branch_labels = depends_on = None


def normalize(value):
    # Bản sao đóng băng của models.catalog.normalize_food_text, để thay đổi sau này của app không làm đổi migration này.
    value = unicodedata.normalize("NFD", (value or "").lower().replace("đ", "d"))
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def upgrade():
    op.execute("ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS page_end integer, ADD COLUMN IF NOT EXISTS page_label text")
    op.execute("UPDATE knowledge_chunks SET page_end = page WHERE page_end IS NULL AND page IS NOT NULL")
    op.execute("""CREATE OR REPLACE FUNCTION knowledge_ts_config(lang text) RETURNS regconfig
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $$ SELECT CASE WHEN lang = 'en' THEN 'english'::regconfig ELSE 'simple'::regconfig END $$""")
    op.execute("""CREATE OR REPLACE FUNCTION knowledge_document(lang text, heading text, content text) RETURNS tsvector
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $$ SELECT setweight(to_tsvector(knowledge_ts_config(lang), coalesce(heading, '')), 'A')
                  || setweight(to_tsvector(knowledge_ts_config(lang), coalesce(content, '')), 'B') $$""")
    # '&' gắn chặt hơn '|' và '<->' gắn chặt hơn cả hai, nên cụm từ có gạch nối được giữ nguyên.
    # Câu hỏi chỉ gồm stop word cho ra NULL, không khớp gì (tsquery rỗng sẽ ghi một NOTICE).
    op.execute("""CREATE OR REPLACE FUNCTION knowledge_query(lang text, q text) RETURNS tsquery
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $$ SELECT CASE WHEN numnode(plainto_tsquery(knowledge_ts_config(lang), q)) = 0 THEN NULL::tsquery
                  ELSE replace(plainto_tsquery(knowledge_ts_config(lang), q)::text, ' & ', ' | ')::tsquery END $$""")
    rebuild("knowledge_document(:lang, :heading, :content)")


def downgrade():
    rebuild("to_tsvector('simple', :content)")
    op.execute("DROP FUNCTION IF EXISTS knowledge_query(text, text)")
    op.execute("DROP FUNCTION IF EXISTS knowledge_document(text, text, text)")
    op.execute("DROP FUNCTION IF EXISTS knowledge_ts_config(text)")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS page_label, DROP COLUMN IF EXISTS page_end")


def rebuild(expression):
    bind = op.get_bind()
    rows = bind.execute(text("""SELECT c.id, c.heading, c.content, r.metadata->>'language' AS lang
        FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id = c.revision_id""")).mappings().all()
    if rows:
        bind.execute(text(f"UPDATE knowledge_chunks SET search_vector = {expression} WHERE id = :id"),
                     [{"id": row["id"], "lang": row["lang"], "heading": normalize(row["heading"]),
                       "content": normalize(row["content"])} for row in rows])
