from contextlib import asynccontextmanager

from agentic.observability import annotate
from agentic.services import mode


class BudgetExceeded(Exception):
    pass


@asynccontextmanager
async def research_lease(store, state):
    async with store.pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("research:" + state["user_id"],),
            )
            row = await (
                await conn.execute(
                    "SELECT * FROM agent_research_budgets WHERE run_id=%s FOR UPDATE",
                    (state["run_id"],),
                )
            ).fetchone()
            active = await (
                await conn.execute(
                    """SELECT 1 FROM agent_research_budgets WHERE user_id=%s
                AND lease_until>now() AND run_id<>%s LIMIT 1""",
                    (state["user_id"], state["run_id"]),
                )
            ).fetchone()
            count = await (
                await conn.execute(
                    "SELECT count(*) AS n FROM agent_research_budgets WHERE user_id=%s AND created_at>now()-interval '1 minute'",
                    (state["user_id"],),
                )
            ).fetchone()
            if active or (not row and count["n"] >= 5):
                raise BudgetExceeded("Research rate limit")
            await conn.execute(
                """INSERT INTO agent_research_budgets(run_id,user_id,session_id,lease_until)
                VALUES (%s,%s,%s,now()+interval '65 seconds') ON CONFLICT(run_id) DO UPDATE
                SET lease_until=now()+interval '65 seconds' """,
                (state["run_id"], state["user_id"], state["session_id"]),
            )
    try:
        yield
    finally:
        async with store.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_research_budgets SET lease_until=NULL WHERE run_id=%s",
                (state["run_id"],),
            )


async def reserve(store, run_id, kind):
    # Chế độ Plan cho thêm lượt tra cứu, lượt trích xuất và vòng tra cứu (services/mode.py).
    limits = mode.policy().research_limits
    if kind not in limits:
        raise ValueError("Unknown budget")
    async with store.pool.connection() as conn:
        row = await (
            await conn.execute(
                f"""UPDATE agent_research_budgets SET {kind}={kind}+1
            WHERE run_id=%s AND {kind}<%s AND lease_until>now() RETURNING {kind}""",
                (run_id, limits[kind]),
            )
        ).fetchone()
        if not row:
            annotate(budget_exceeded=True, budget_kind=kind)
            raise BudgetExceeded(kind)


def admit(documents, identifiers):
    """Các id được nhận (id đã có luôn được nhận lại); thêm id mới vào documents khi loại của nó còn chỗ.

    Mỗi lượt tối đa mode.ModePolicy.documents đoạn trích cơ sở tri thức (id 'kb:') và chừng ấy nguồn web, tính
    riêng: các đoạn trích nội bộ không bao giờ chiếm chỗ của lần tra cứu web bổ sung."""
    limit = mode.policy().documents
    accepted = []
    for ident in identifiers:
        local = ident.startswith("kb:")
        if ident in documents:
            accepted.append(ident)
        elif sum(d.startswith("kb:") == local for d in documents) < limit:
            documents.append(ident)
            accepted.append(ident)
    return accepted


async def reserve_documents(store, run_id, identifiers):
    async with store.pool.connection() as conn:
        async with conn.transaction():
            row = await (
                await conn.execute(
                    "SELECT documents FROM agent_research_budgets WHERE run_id=%s FOR UPDATE",
                    (run_id,),
                )
            ).fetchone()
            if not row:
                raise BudgetExceeded("Missing research budget")
            documents = list(row["documents"])
            accepted = admit(documents, identifiers)
            from psycopg.types.json import Jsonb

            await conn.execute(
                "UPDATE agent_research_budgets SET documents=%s WHERE run_id=%s",
                (Jsonb(documents), run_id),
            )
            return accepted
