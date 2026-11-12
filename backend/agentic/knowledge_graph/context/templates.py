"""Bộ nhớ mẫu truy vấn: mẫu viết tay (seed), rồi mẫu đã học theo vân tay, rồi mới sinh mới.

Text-to-Cypher thêm một lời gọi model; phần lớn câu hỏi lặp lại cùng hình dạng (intent × focus × độ hạt thời gian),
nên hình dạng đã chạy được được lưu lại và dùng lại không cần model. Mẫu chỉ là văn bản truy vấn đã qua validator,
không bao giờ chứa giá trị tham số (chủ sở hữu, ngày, từ khoá) hay câu hỏi của người dùng. Seed viết không có owner_id:
validator tự gắn phạm vi người dùng, như với truy vấn sinh ra.
"""

import logging
from dataclasses import dataclass

from ..schema import SCHEMA_VERSION

log = logging.getLogger(__name__)
NUTRITION = frozenset({"meals", "foods", "progress"})
TRAINING = frozenset({"trainings", "exercises", "coaching", "training_plans"})
BODY = frozenset({"metrics", "profile"})
ANY = frozenset({"*"})
ALL_FOCUS = frozenset({"summary", "list", "top", "trend", "latest", "relation", "followup"})
ALL_GRAINS = frozenset({"day", "week", "month"})
# Mẫu bị cách ly sau ngần này lần lỗi khi số lỗi vượt số lần chạy được.
QUARANTINE_FAILURES = 2
TRUSTED_HITS = 2


@dataclass(frozen=True)
class Seed:
    id: str
    domains: frozenset
    focus: frozenset
    cypher: str
    grains: frozenset = ALL_GRAINS
    terms: bool | None = None  # True: cần từ khoá, False: chỉ khi không có, None: cả hai


SEEDS = (
    Seed(
        "session.trace",
        ANY,
        frozenset({"followup"}),
        """MATCH (r:Run {session_id: $session_id})
OPTIONAL MATCH (r)-[:HAS_EXECUTION]->(e:Execution)
WITH r, collect(e.tool + coalesce(' (' + e.args + ')', '') + coalesce(' → ' + e.outcome, '')) AS buoc
RETURN r.at AS luc, r.intent_label AS y_dinh, r.status AS trang_thai, r.decision AS quyet_dinh,
       r.edited_fields AS da_sua, buoc
ORDER BY luc DESC LIMIT 6""",
    ),
    Seed(
        "foods.history",
        NUTRITION,
        ALL_FOCUS - {"followup"},
        """MATCH (m:Meal)-[:HAS_ITEM]->(i:MealItem)-[:REFERS_TO]->(f:Food)
WHERE m.local_date >= $start AND m.local_date <= $end AND any(t IN $terms WHERE f.name_search CONTAINS t)
RETURN m.local_date AS ngay, m.local_time AS gio, m.name AS bua, f.name_vi AS mon, i.quantity AS luong,
       i.unit AS don_vi, i.energy_kcal AS kcal, i.protein_g AS protein_g
ORDER BY m.at DESC LIMIT 20""",
        terms=True,
    ),
    Seed(
        "exercise.history",
        TRAINING,
        ALL_FOCUS - {"followup"},
        """MATCH (t:Training)-[p:PERFORMED]->(x:Exercise)
WHERE t.local_date >= $start AND t.local_date <= $end AND any(term IN $terms WHERE x.name_search CONTAINS term)
RETURN t.local_date AS ngay, x.name_vi AS bai_tap, p.hard_sets AS hiep, p.volume_kg AS volume_kg,
       p.best_e1rm_kg AS e1rm_kg, p.distance_km AS km, p.duration_min AS phut
ORDER BY t.at DESC LIMIT 20""",
        terms=True,
    ),
    Seed(
        "health.days",
        ANY,
        frozenset({"relation"}),
        """MATCH (d:Day) WHERE d.date >= $start AND d.date <= $end
RETURN d.date AS ngay, d.kcal AS kcal_an, d.training_load AS tai_tap, d.training_minutes AS phut_tap,
       d.sleep_minutes AS phut_ngu, d.resting_hr_bpm AS nhip_nghi, d.hrv_ms AS hrv_ms, d.steps AS buoc,
       d.weight_kg AS can_kg
ORDER BY ngay LIMIT 31""",
        grains=frozenset({"day"}),
    ),
    Seed(
        "health.periods",
        ANY,
        frozenset({"relation"}),
        """MATCH (p:Period {grain: $grain}) WHERE p.start <= $end AND p.end >= $start
RETURN p.label AS ky, p.kcal_avg AS kcal_an_tb, p.training_load AS tai_tap, p.sleep_avg_minutes AS ngu_tb_phut,
       p.steps_avg AS buoc_tb, p.weight_start AS can_dau, p.weight_end AS can_cuoi
ORDER BY p.start LIMIT 24""",
        grains=frozenset({"week", "month"}),
    ),
    Seed(
        "meals.list",
        NUTRITION,
        frozenset({"list", "latest"}),
        """MATCH (m:Meal) WHERE m.local_date >= $start AND m.local_date <= $end
OPTIONAL MATCH (m)-[:HAS_ITEM]->(i:MealItem)
WITH m, collect(i.food_name + ' ' + toString(i.quantity) + toLower(i.unit)) AS mon
RETURN m.local_date AS ngay, m.local_time AS gio, m.name AS bua, mon, m.energy_kcal AS kcal,
       m.protein_g AS protein_g
ORDER BY m.at DESC LIMIT 25""",
        grains=frozenset({"day"}),
        terms=False,
    ),
    Seed(
        "foods.top",
        NUTRITION,
        frozenset({"top"}),
        """MATCH (m:Meal)-[:HAS_ITEM]->(i:MealItem)
WHERE m.local_date >= $start AND m.local_date <= $end
RETURN i.food_name AS mon, count(i) AS so_lan, round(sum(i.energy_kcal)) AS kcal,
       round(sum(i.protein_g), 1) AS protein_g
ORDER BY kcal DESC LIMIT 10""",
        terms=False,
    ),
    Seed(
        "nutrition.days",
        NUTRITION,
        ALL_FOCUS,
        """MATCH (d:Day) WHERE d.date >= $start AND d.date <= $end AND d.meals > 0
RETURN d.date AS ngay, d.meals AS so_bua, d.kcal AS kcal, d.protein_g AS protein_g, d.carbohydrate_g AS carb_g,
       d.fat_g AS fat_g
ORDER BY ngay DESC LIMIT 31""",
        grains=frozenset({"day"}),
        terms=False,
    ),
    Seed(
        "nutrition.periods",
        NUTRITION,
        ALL_FOCUS,
        """MATCH (p:Period {grain: $grain}) WHERE p.start <= $end AND p.end >= $start
RETURN p.label AS ky, p.days_with_meals AS ngay_co_ghi, p.kcal_avg AS kcal_tb, p.protein_avg AS protein_tb,
       p.weight_start AS can_dau, p.weight_end AS can_cuoi
ORDER BY p.start LIMIT 24""",
        grains=frozenset({"week", "month"}),
        terms=False,
    ),
    Seed(
        "exercise.top",
        TRAINING,
        frozenset({"top"}),
        """MATCH (t:Training)-[p:PERFORMED]->(x:Exercise)
WHERE t.local_date >= $start AND t.local_date <= $end
RETURN x.name_vi AS bai_tap, count(t) AS so_buoi, max(p.best_e1rm_kg) AS e1rm_max_kg,
       round(sum(p.distance_km), 1) AS km
ORDER BY so_buoi DESC LIMIT 10""",
        terms=False,
    ),
    Seed(
        "trainings.list",
        TRAINING,
        ALL_FOCUS,
        """MATCH (t:Training) WHERE t.local_date >= $start AND t.local_date <= $end
OPTIONAL MATCH (t)-[:PERFORMED]->(x:Exercise)
WITH t, collect(x.name_vi) AS bai_tap
RETURN t.local_date AS ngay, t.local_time AS gio, t.name AS buoi, t.discipline AS loai, t.duration_min AS phut,
       t.session_rpe AS rpe, t.training_load AS tai, bai_tap
ORDER BY t.at DESC LIMIT 20""",
        grains=frozenset({"day"}),
        terms=False,
    ),
    Seed(
        "training.periods",
        TRAINING,
        ALL_FOCUS,
        """MATCH (p:Period {grain: $grain}) WHERE p.start <= $end AND p.end >= $start
RETURN p.label AS ky, p.trainings AS so_buoi, p.training_minutes AS phut, p.training_load AS tai
ORDER BY p.start LIMIT 24""",
        grains=frozenset({"week", "month"}),
        terms=False,
    ),
    Seed(
        "body.latest",
        BODY,
        frozenset({"latest"}),
        """MATCH (d:Day) WHERE d.date <= $end AND d.weight_kg IS NOT NULL
RETURN d.date AS ngay, d.weight_kg AS can_kg
ORDER BY ngay DESC LIMIT 3""",
    ),
    Seed(
        "body.metrics",
        BODY,
        ALL_FOCUS,
        """MATCH (b:BodyMetric) WHERE b.local_date >= $start AND b.local_date <= $end
RETURN b.local_date AS ngay, b.weight_kg AS can_kg, b.body_fat_pct AS mo_pct, b.muscle_mass_kg AS co_kg,
       b.height_cm AS cao_cm
ORDER BY b.at DESC LIMIT 30""",
        grains=frozenset({"day"}),
    ),
    Seed(
        "body.days",
        BODY,
        ALL_FOCUS,
        """MATCH (d:Day) WHERE d.date >= $start AND d.date <= $end AND d.weight_kg IS NOT NULL
RETURN d.date AS ngay, d.weight_kg AS can_kg
ORDER BY ngay LIMIT 50""",
        grains=frozenset({"week", "month"}),
    ),
    Seed(
        "goals",
        frozenset({"goals"}),
        ALL_FOCUS,
        """MATCH (g:Goal)
WHERE g.status = 'IN_PROGRESS' OR (g.start_date <= $end AND coalesce(g.target_date, $end) >= $start)
RETURN g.title AS muc_tieu, g.status AS trang_thai, g.goal_types AS loai, g.start_date AS bat_dau,
       g.target_date AS han, g.weight_kg_target AS can_dich
ORDER BY bat_dau DESC LIMIT 10""",
    ),
    Seed(
        "health.days.default",
        frozenset({"health"}),
        ALL_FOCUS,
        """MATCH (d:Day) WHERE d.date >= $start AND d.date <= $end
RETURN d.date AS ngay, d.steps AS buoc, d.active_minutes AS phut_van_dong, d.sleep_minutes AS phut_ngu,
       d.resting_hr_bpm AS nhip_nghi, d.hrv_ms AS hrv_ms, d.total_kcal AS kcal_tieu_hao, d.kcal AS kcal_an
ORDER BY ngay LIMIT 31""",
        grains=frozenset({"day"}),
    ),
    Seed(
        "health.periods.default",
        frozenset({"health"}),
        ALL_FOCUS,
        """MATCH (p:Period {grain: $grain}) WHERE p.start <= $end AND p.end >= $start
RETURN p.label AS ky, p.steps_avg AS buoc_tb, p.sleep_avg_minutes AS ngu_tb_phut, p.training_load AS tai_tap,
       p.kcal_avg AS kcal_an_tb
ORDER BY p.start LIMIT 24""",
        grains=frozenset({"week", "month"}),
    ),
)
SEEDS_BY_ID = {seed.id: seed for seed in SEEDS}


def seed_for(domain, focus, grain, has_terms):
    for seed in SEEDS:
        if (
            ("*" in seed.domains or domain in seed.domains)
            and focus in seed.focus
            and grain in seed.grains
            and (seed.terms is None or seed.terms == has_terms)
        ):
            return seed
    return None


def fingerprint(intent, domain, focus, grain, has_terms):
    """Hình dạng của câu hỏi, không có giá trị nào: hai câu cùng hình dạng dùng chung một truy vấn."""
    return f"v{SCHEMA_VERSION}|{intent or '-'}|{domain or '-'}|{focus}|{grain}|{'terms' if has_terms else '-'}"


# ---------------------------------------------------------------- mẫu đã học (PostgreSQL của agent)


async def learned(pool, key):
    if pool is None:
        return None
    async with pool.connection() as conn:
        return await (
            await conn.execute(
                """SELECT cypher, status FROM kg_query_templates
                WHERE fingerprint=%s AND schema_version=%s AND status <> 'quarantined'""",
                (key, SCHEMA_VERSION),
            )
        ).fetchone()


async def remember(pool, key, cypher):
    """Lưu truy vấn sinh ra đã chạy được; thay mẫu cũ đã bị cách ly hoặc của lược đồ cũ."""
    if pool is None:
        return
    async with pool.connection() as conn:
        await conn.execute(
            """INSERT INTO kg_query_templates (fingerprint, cypher, schema_version, hits)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (fingerprint) DO UPDATE SET cypher=EXCLUDED.cypher, schema_version=EXCLUDED.schema_version,
                status='candidate', hits=1, failures=0, last_error=NULL, updated_at=now()
            WHERE kg_query_templates.status='quarantined'
               OR kg_query_templates.schema_version <> EXCLUDED.schema_version""",
            (key, cypher, SCHEMA_VERSION),
        )


async def record(pool, key, ok, error=None):
    """Kết quả một lần dùng mẫu đã học: chạy được thì tin dần, lỗi lặp lại thì cách ly để lần sau sinh lại."""
    if pool is None:
        return
    async with pool.connection() as conn:
        await conn.execute(
            """UPDATE kg_query_templates SET
                hits = hits + %s, failures = failures + %s, last_error = COALESCE(%s, last_error), updated_at = now(),
                status = CASE
                    WHEN failures + %s >= %s AND failures + %s > hits + %s THEN 'quarantined'
                    WHEN hits + %s >= %s THEN 'trusted' ELSE status END
            WHERE fingerprint = %s""",
            (
                int(ok),
                int(not ok),
                error,
                int(not ok),
                QUARANTINE_FAILURES,
                int(not ok),
                int(ok),
                int(ok),
                TRUSTED_HITS,
                key,
            ),
        )


async def warm_list(pool, limit=30):
    if pool is None:
        return []
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT cypher FROM kg_query_templates WHERE schema_version=%s AND status <> 'quarantined'
                ORDER BY hits DESC LIMIT %s""",
                (SCHEMA_VERSION, limit),
            )
        ).fetchall()
    return [row["cypher"] for row in rows]
