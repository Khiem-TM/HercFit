"""Private model context: generation-scoped, expiring, never a user history source."""

from psycopg.types.json import Jsonb


class ContextStore:
    async def latest_revocation(self, user_id):
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    """SELECT COALESCE(MAX((payload->>'version')::bigint),0) AS version FROM domain_events
                WHERE user_id=%s AND topic='consent.changed' AND payload->>'purpose'='assistant'
                AND payload->>'granted'='false'""",
                    (user_id,),
                )
            ).fetchone()
        return row["version"]

    async def reset_model_context(self, session_id, version):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT session_id FROM agent_session_generations WHERE session_id=%s FOR UPDATE",
                    (session_id,),
                )
                await conn.execute(
                    "SELECT session_id FROM agent_sessions WHERE session_id=%s FOR UPDATE",
                    (session_id,),
                )
                await conn.execute(
                    "DELETE FROM agent_model_context WHERE session_id=%s", (session_id,)
                )
                await conn.execute(
                    "UPDATE agent_actions SET status='superseded' WHERE session_id=%s AND status='pending'",
                    (session_id,),
                )
                await conn.execute(
                    "UPDATE agent_sessions SET thread_id=NULL,memory_consent_version=%s,"
                    "memory_cleanup_pending=true,memory_cache_cleanup_pending=true WHERE session_id=%s",
                    (version, session_id),
                )
                row = await (
                    await conn.execute(
                        "UPDATE agent_session_generations SET generation=generation+1,updated_at=now() "
                        "WHERE session_id=%s RETURNING generation",
                        (session_id,),
                    )
                ).fetchone()
                return row["generation"]

    async def finish_context_cleanup(self, session_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_sessions SET memory_cleanup_pending=false WHERE session_id=%s",
                (session_id,),
            )

    async def recovery_action(self, session_id):
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    "SELECT * FROM agent_actions WHERE session_id=%s AND status IN ('approved','executed') "
                    "AND response IS NULL ORDER BY created_at LIMIT 1",
                    (session_id,),
                )
            ).fetchone()

    async def finish_cache_cleanup(self, session_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_sessions SET memory_cache_cleanup_pending=false WHERE session_id=%s",
                (session_id,),
            )

    async def model_context(self, session_id, user_id, generation):
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT c.data FROM agent_model_context c JOIN agent_sessions s USING(session_id) "
                    "JOIN agent_session_generations g USING(session_id) WHERE c.session_id=%s AND s.user_id=%s "
                    "AND c.generation=%s AND c.generation=g.generation AND c.expires_at>now()",
                    (session_id, user_id, generation),
                )
            ).fetchone()
        return row["data"] if row else None

    async def save_model_context(self, session_id, user_id, generation, data, ttl):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                # Same row lock as archive/reset: an old summary cannot revive a revoked generation.
                owner = await (
                    await conn.execute(
                        "SELECT s.user_id,g.generation FROM agent_sessions s JOIN agent_session_generations g USING(session_id) "
                        "WHERE s.session_id=%s FOR UPDATE OF s",
                        (session_id,),
                    )
                ).fetchone()
                if (
                    not owner
                    or str(owner["user_id"]) != str(user_id)
                    or owner["generation"] != generation
                ):
                    return
                await conn.execute(
                    "INSERT INTO agent_model_context VALUES (%s,%s,%s,now()+make_interval(secs => %s)) "
                    "ON CONFLICT(session_id) DO UPDATE SET generation=excluded.generation,data=excluded.data,expires_at=excluded.expires_at",
                    (session_id, generation, Jsonb(data), ttl),
                )

    async def prune_model_context(self):
        async with self.pool.connection() as conn:
            return (
                await conn.execute("DELETE FROM agent_model_context WHERE expires_at<=now()")
            ).rowcount
