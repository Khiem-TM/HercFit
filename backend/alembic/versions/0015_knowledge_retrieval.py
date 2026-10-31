"""Knowledge retrieval: language-aware weighted full-text search and page spans.

* knowledge_document(lang, heading, content) builds the chunk tsvector: the chapter
  heading weighs 'A' and the passage 'B'; English documents use the stemming
  'english' configuration (stop words removed), others stay on 'simple'.
* knowledge_query(lang, q) turns a natural-language question into an OR of its
  lexemes. The former plainto_tsquery AND required every word of the question in
  one chunk and matched almost nothing.
* knowledge_chunks gains page_end (a chunk may span pages) and page_label (the
  printed page, when the source spec can map it).

Text is normalized in Python (lower case, no diacritics) before it reaches these
functions, at ingestion and at query time, exactly as before.
"""
import unicodedata

from alembic import op
from sqlalchemy import text

revision = "0015_knowledge_retrieval"
down_revision = "0014_google_health"
branch_labels = depends_on = None


def normalize(value):
    # Frozen copy of models.catalog.normalize_food_text, so later app changes cannot alter this migration.
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
    # '&' binds tighter than '|' and '<->' tighter than both, so hyphenated phrases stay intact.
    # A question of stop words only yields NULL, which matches nothing (an empty tsquery logs a NOTICE).
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
