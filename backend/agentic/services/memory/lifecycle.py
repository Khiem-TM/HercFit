"""User history survives context revocation; execution recovery keeps only an approved command.

All methods run under Store.session's lease. The cleanup marker makes a crash
between SQL invalidation and checkpoint/Redis deletion retryable and fail closed.
"""

from hashlib import sha256
from uuid import uuid4

from langchain_core.messages import AIMessage

from agentic.agents.state import initial_state
from agentic.services.memory.transcript import AGENT, visible


class MemoryLifecycle:
    async def archive(self, snapshot):
        archive = getattr(self.store, "archive_snapshot", None)
        if archive and snapshot and snapshot.values:
            await archive(snapshot.values)
            if snapshot.values.get("status") == "pending_confirmation":
                await self.archive_reply(snapshot.values, self.response(snapshot.values))

    async def archive_reply(self, values, result):
        archive = getattr(self.store, "archive_snapshot", None)
        if not archive or not result.reply:
            return
        messages = visible(values.get("messages"))
        if messages and messages[-1].type == "ai" and messages[-1].content == result.reply:
            return
        # Preview/error replies are visible too, but need not be model messages.
        reply_id = "reply:" + result.run_id + ":" + sha256(result.reply.encode()).hexdigest()
        await archive(
            {**values, "messages": [AIMessage(id=reply_id, content=result.reply, name=AGENT)]}
        )

    async def prepare_session(self, session, user_id):
        # Small in-memory evaluation stores do not implement durable history.
        if not hasattr(self.store, "archive_snapshot"):
            return
        session_id = session["session_id"]
        if not session.get("transcript_migrated"):
            for thread in await self.store.threads(session_id):
                snapshot = await self.state(thread)
                if snapshot and snapshot.values:
                    await self.store.archive_snapshot(snapshot.values, legacy=True)
            await self.store.history_migrated(session_id)
            session["transcript_migrated"] = True
        else:
            await self.archive(await self.state(session.get("thread_id")))

        version = await self.store.latest_revocation(user_id)
        if version > session.get("memory_consent_version", 0):
            session["generation"] = await self.store.reset_model_context(session_id, version)
            session.update(
                thread_id=None,
                memory_consent_version=version,
                memory_cleanup_pending=True,
                memory_cache_cleanup_pending=True,
            )
        if session.get("memory_cleanup_pending"):
            for thread in await self.store.threads(session_id):
                await self.saver.adelete_thread(thread)
                await self.store.forget_thread(thread)
            await self.store.finish_context_cleanup(session_id)
            session["memory_cleanup_pending"] = False
        if session.get("memory_cache_cleanup_pending") and self.memory:
            if await self.memory.forget(session_id):
                await self.store.finish_cache_cleanup(session_id)
                session["memory_cache_cleanup_pending"] = False

        # The action ledger survives context cleanup. Rebuild only the immutable
        # approved command, never old messages, summaries, previews or tool reads.
        if not session.get("thread_id"):
            row = await self.store.recovery_action(session_id)
            if row:
                thread_id = str(uuid4())
                clean = initial_state(
                    messages=[],
                    user_id=user_id,
                    session_id=session_id,
                    run_id=thread_id,
                    generation=session["generation"],
                    previous={},
                    memory=None,
                )
                action = {
                    key: row["data"].get(key)
                    for key in (
                        "action_id",
                        "session_id",
                        "user_id",
                        "tool",
                        "payload",
                        "payload_hash",
                        "revision",
                        "expires_at",
                        "research_id",
                    )
                }
                clean.update(
                    pending_action={**action, "preview": "Khôi phục thao tác đã duyệt."},
                    approved=True,
                    action_decision="approved",
                    status="pending_confirmation",
                )
                await self.graph.aupdate_state(
                    self.config(thread_id), clean, as_node="confirmation"
                )
                await self.store.bind(session_id, thread_id)
                session["thread_id"] = thread_id
