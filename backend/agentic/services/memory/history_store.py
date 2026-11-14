"""Durable user transcript. Never use this archive to rebuild model context.

All runtime callers hold the session lease. FK deletion follows chat/account
erasure; checkpoint retention and consent revocation do not delete the archive.
"""

from hashlib import sha256

from psycopg.types.json import Jsonb

from agentic.services.memory.transcript import visible


class HistoryStore:
    async def archive_snapshot(self, values, *, legacy=False):
        if not values.get("session_id") or not values.get("user_id"):
            return
        async with self.pool.connection() as conn:
            async with conn.transaction():
                owner = await (
                    await conn.execute(
                        "SELECT s.user_id,g.generation FROM agent_sessions s "
                        "JOIN agent_session_generations g USING(session_id) WHERE s.session_id=%s FOR UPDATE OF s",
                        (values["session_id"],),
                    )
                ).fetchone()
                if not owner or str(owner["user_id"]) != str(values["user_id"]):
                    return
                if not legacy and owner["generation"] != values.get("session_generation", 1):
                    return  # A late checkpoint must not resurrect an erased generation.
                for index, message in enumerate(visible(values.get("messages"))):
                    if message.type not in {"human", "ai"}:
                        continue
                    message_id = (
                        message.id
                        or sha256(
                            f"{values.get('run_id')}:{index}:{message.type}:{message.content}".encode()
                        ).hexdigest()
                    )
                    await conn.execute(
                        """INSERT INTO agent_transcript_messages(session_id,user_id,message_id,role,content,name)
                        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (session_id,message_id) DO NOTHING""",
                        (
                            values["session_id"],
                            values["user_id"],
                            message_id,
                            message.type,
                            Jsonb(message.content),
                            getattr(message, "name", None),
                        ),
                    )

    async def transcript(self, session_id, user_id):
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    """SELECT m.message_id AS id,m.role,m.content,m.name,m.created_at
                FROM agent_transcript_messages m JOIN agent_sessions s USING(session_id)
                WHERE m.session_id=%s AND m.user_id=%s AND s.user_id=%s ORDER BY m.seq""",
                    (session_id, user_id, user_id),
                )
            ).fetchall()

    async def history_migrated(self, session_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_sessions SET transcript_migrated=true WHERE session_id=%s",
                (session_id,),
            )
