import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from agentic.observability import durable_context
from agentic.observability.persistence import set_psycopg_context
from agentic.services.memory.turns import turn_record
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE


def usage_day(now=None):
    """Ngày hạn mức theo múi giờ ứng dụng, không phụ thuộc TZ của container."""
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()


def payload_hash(tool, payload):
    return sha256(
        json.dumps(
            [tool, payload], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


class SessionBusy(HTTPException):
    def __init__(self):
        super().__init__(
            409, "Cuộc trò chuyện đang xử lý một yêu cầu khác; vui lòng thử lại sau ít giây."
        )


class Store:
    def __init__(self, pool, lock_pool=None, lease_seconds=180, wait_seconds=30):
        self.pool = pool
        self.lock_pool = lock_pool or pool  # giữ cho các bên gọi vẫn truyền nó
        self.lease_seconds, self.wait_seconds = lease_seconds, wait_seconds

    async def ready(self):
        from agentic.migrations.runner import EXPECTED_SCHEMA_VERSION

        async with self.pool.connection() as conn:
            result = await (
                await conn.execute(
                    "SELECT version FROM agent_schema_version WHERE version=%s",
                    (EXPECTED_SCHEMA_VERSION,),
                )
            ).fetchone()
            if not result:
                raise RuntimeError("Run python -m agentic.scripts.migrate before starting")

    async def _acquire(self, session_id, user_id, create, token):
        """Một transaction ngắn: kiểm tra quyền sở hữu, tạo mới (tuỳ chọn), rồi lấy lease."""
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                if create:
                    generation = await (
                        await conn.execute(
                            "SELECT * FROM agent_session_generations WHERE session_id=%s FOR UPDATE",
                            (session_id,),
                        )
                    ).fetchone()
                    if generation and str(generation["user_id"]) != user_id:
                        raise HTTPException(404, "Session not found")
                    await conn.execute(
                        "INSERT INTO agent_sessions(session_id,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (session_id, user_id),
                    )
                    await conn.execute(
                        """INSERT INTO agent_session_generations(session_id,user_id) VALUES (%s,%s)
                        ON CONFLICT (session_id) DO UPDATE SET
                        generation=agent_session_generations.generation + CASE WHEN agent_session_generations.deleted THEN 1 ELSE 0 END,
                        deleted=false, updated_at=now()""",
                        (session_id, user_id),
                    )
                owner = await (
                    await conn.execute(
                        "SELECT user_id FROM agent_sessions WHERE session_id=%s", (session_id,)
                    )
                ).fetchone()
                if not owner or str(owner["user_id"]) != user_id:
                    raise HTTPException(404, "Session not found")
                acquired = await (
                    await conn.execute(
                        """UPDATE agent_sessions SET lease_token=%s,
                    lease_until=now() + make_interval(secs => %s)
                    WHERE session_id=%s AND (lease_until IS NULL OR lease_until < now()) RETURNING session_id""",
                        (token, self.lease_seconds, session_id),
                    )
                ).fetchone()
                if not acquired:
                    return None
                return await (
                    await conn.execute(
                        """SELECT s.*,g.generation FROM agent_sessions s
                    JOIN agent_session_generations g USING(session_id) WHERE s.session_id=%s""",
                        (session_id,),
                    )
                ).fetchone()

    @asynccontextmanager
    async def session(self, session_id, user_id, create=True):
        # Một lease có thời hạn tuần tự hoá từng thao tác chat/confirm/history/clear trên một
        # cuộc trò chuyện giữa các worker, mà không giữ kết nối trong pool trong lúc
        # model chạy. Lease của worker bị sập đơn giản là hết hạn.
        token = uuid4()
        deadline = monotonic() + self.wait_seconds
        while True:
            row = await self._acquire(session_id, user_id, create, token)
            if row is not None:
                break
            if monotonic() >= deadline:
                raise SessionBusy()
            await asyncio.sleep(0.2)
        try:
            yield row
        finally:
            async with self.pool.connection() as conn:
                await conn.execute(
                    "UPDATE agent_sessions SET lease_token=NULL, lease_until=NULL WHERE session_id=%s AND lease_token=%s",
                    (session_id, token),
                )

    async def bind(self, session_id, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO agent_threads(thread_id,session_id,needs_reconcile,last_run_at) VALUES (%s,%s,true,now())",
                (thread_id, session_id),
            )
            await conn.execute(
                "UPDATE agent_sessions SET thread_id=%s WHERE session_id=%s",
                (thread_id, session_id),
            )

    async def touch_thread(self, thread_id):
        """Lượt chạy được tiếp tục (xác nhận) có thể đổi checkpoint: đối soát lại sau nếu cần."""
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_threads SET needs_reconcile=true, last_run_at=now() WHERE thread_id=%s",
                (thread_id,),
            )

    async def mark_reconciled(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_threads SET needs_reconcile=false, kg_checked_at=now() WHERE thread_id=%s",
                (thread_id,),
            )

    async def update_session_meta(self, session_id, *, title, last_message, message_count, status):
        async with self.pool.connection() as conn:
            await conn.execute(
                """UPDATE agent_sessions SET title=COALESCE(title, %s), last_message=%s,
                last_interaction_at=now(), message_count=%s, last_status=%s WHERE session_id=%s""",
                (title, last_message, message_count, status, session_id),
            )

    async def consume_turn(self, user_id, *, turn_limit, token_limit, day=None):
        """Đếm nguyên tử một lượt mới; False khi đã hết ngân sách lượt hoặc token của hôm nay."""
        day = day or usage_day()
        async with self.pool.connection() as conn:
            async with conn.transaction():
                row = await (
                    await conn.execute(
                        """INSERT INTO agent_usage_daily(user_id,day,turns) VALUES (%s,%s,0)
                    ON CONFLICT (user_id,day) DO UPDATE SET updated_at=now() RETURNING turns,input_tokens,output_tokens""",
                        (user_id, day),
                    )
                ).fetchone()
                if (turn_limit and row["turns"] >= turn_limit) or (
                    token_limit and row["input_tokens"] + row["output_tokens"] >= token_limit
                ):
                    return False
                await conn.execute(
                    "UPDATE agent_usage_daily SET turns=turns+1, updated_at=now() WHERE user_id=%s AND day=%s",
                    (user_id, day),
                )
                return True

    async def add_usage(self, user_id, input_tokens, output_tokens, day=None):
        async with self.pool.connection() as conn:
            await conn.execute(
                """INSERT INTO agent_usage_daily(user_id,day,input_tokens,output_tokens) VALUES (%s,%s,%s,%s)
                ON CONFLICT (user_id,day) DO UPDATE SET input_tokens=agent_usage_daily.input_tokens+EXCLUDED.input_tokens,
                output_tokens=agent_usage_daily.output_tokens+EXCLUDED.output_tokens, updated_at=now()""",
                (user_id, day or usage_day(), int(input_tokens or 0), int(output_tokens or 0)),
            )

    async def user_session_ids(self, user_id):
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT session_id FROM agent_sessions WHERE user_id=%s", (user_id,)
                )
            ).fetchall()
            return [r["session_id"] for r in rows]

    async def stale_threads(self, older_than_days, limit=500):
        """Các thread theo lượt đã bị thay thế cũ hơn cửa sổ lưu giữ (không bao giờ là thread hiện tại của phiên)."""
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    """SELECT t.thread_id FROM agent_threads t
                JOIN agent_sessions s USING(session_id)
                WHERE t.last_run_at < now() - make_interval(days => %s) AND t.thread_id IS DISTINCT FROM s.thread_id
                  AND NOT t.needs_reconcile
                ORDER BY t.last_run_at LIMIT %s""",
                    (older_than_days, limit),
                )
            ).fetchall()

    async def forget_thread(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute("DELETE FROM agent_threads WHERE thread_id=%s", (thread_id,))

    async def forget_episodes(self, user_id, is_health):
        """Xoá các episode hội thoại của người dùng mà `is_health(data)` chọn ra.

        Mỗi dòng nhật ký (lượt hoặc lần thực thi tool) nhận một lệnh `delete` của graph ở
        phiên bản kế tiếp, để projector đánh tombstone episode, và chính dòng đó bị
        xoá để dựng lại graph (enqueue_kg_snapshot) không khôi phục được nó.
        """
        removed = {"Run": 0, "Execution": 0}
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                for table, key, aggregate in (
                    ("agent_turn_records", "run_id", "Run"),
                    ("agent_execution_records", "execution_id", "Execution"),
                ):
                    rows = await (
                        await conn.execute(
                            f"SELECT {key} AS id, version, data FROM {table} WHERE user_id=%s FOR UPDATE",
                            (user_id,),
                        )
                    ).fetchall()
                    for row in rows:
                        data = row["data"] or {}
                        if not is_health(data):
                            continue
                        version = row["version"] + 1
                        event_id = uuid5(
                            NAMESPACE_URL, f"agent:{aggregate}:{row['id']}:{version}:delete"
                        )
                        await conn.execute(
                            """INSERT INTO kg_outbox
                            (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                            VALUES (%s,'agent',%s,%s,%s,%s,'delete',now(),%s) ON CONFLICT DO NOTHING""",
                            (
                                event_id,
                                aggregate,
                                str(row["id"]),
                                str(user_id),
                                version,
                                Jsonb(data),
                            ),
                        )
                        await conn.execute(f"DELETE FROM {table} WHERE {key}=%s", (row["id"],))
                        removed[aggregate] += 1
        return removed

    async def new_action(
        self,
        session_id,
        user_id,
        tool,
        payload,
        preview,
        expires_at,
        research_id=None,
        action_id=None,
    ):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                existing = (
                    await (
                        await conn.execute(
                            "SELECT data FROM agent_actions WHERE action_id=%s", (action_id,)
                        )
                    ).fetchone()
                    if action_id
                    else None
                )
                if existing:
                    return existing["data"]
                revision = (
                    await (
                        await conn.execute(
                            "UPDATE agent_sessions SET revision=revision+1 WHERE session_id=%s RETURNING revision",
                            (session_id,),
                        )
                    ).fetchone()
                )["revision"]
                action = dict(
                    action_id=action_id or str(uuid4()),
                    session_id=session_id,
                    user_id=user_id,
                    tool=tool,
                    payload=payload,
                    preview=preview,
                    payload_hash=payload_hash(tool, payload),
                    revision=revision,
                    expires_at=expires_at.isoformat(),
                    research_id=research_id,
                )
                await conn.execute(
                    "INSERT INTO agent_actions(action_id,session_id,user_id,status,data,trace_context) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        action["action_id"],
                        session_id,
                        user_id,
                        "pending",
                        Jsonb(action),
                        Jsonb(durable_context()),
                    ),
                )
                return action

    async def revise_action(self, action_id, changes):
        """Thay payload của hành động còn chờ (người dùng sửa trên thẻ); hành động đã quyết định không đổi."""
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "UPDATE agent_actions SET data=data||%s WHERE action_id=%s AND status='pending' RETURNING data",
                    (Jsonb(changes), action_id),
                )
            ).fetchone()
        if row is None:
            raise HTTPException(409, "Action is no longer pending")
        return row["data"]

    async def action(self, action_id):
        async with self.pool.connection() as conn:
            return await (
                await conn.execute("SELECT * FROM agent_actions WHERE action_id=%s", (action_id,))
            ).fetchone()

    async def set_action(self, action_id, status, response=None):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_actions SET status=%s,response=COALESCE(%s,response) WHERE action_id=%s",
                (status, Jsonb(response) if response is not None else None, action_id),
            )

    async def invalidate(self, session_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_actions SET status='superseded' WHERE session_id=%s AND status='pending'",
                (session_id,),
            )

    async def authorize(self, action):
        row = await self.action(action["action_id"])
        if not row or row["status"] not in {"approved", "executed"}:
            raise HTTPException(409, "Action is not approved")
        saved = row["data"]
        fields = ["user_id", "session_id", "revision", "tool", "payload_hash"]
        if (
            any(saved[k] != action[k] for k in fields)
            or payload_hash(action["tool"], action["payload"]) != saved["payload_hash"]
        ):
            raise HTTPException(409, "Approved payload has changed")
        # Hạn được kiểm tra lúc phê duyệt. Lệnh ghi đã được chấp nhận có thể thử lại
        # sau sự cố với CÙNG khoá idempotency kể cả sau hạn đó.
        return saved

    async def research(self, state, candidate):
        research_id = str(uuid4())
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO agent_research(research_id,user_id,session_id,data) VALUES (%s,%s,%s,%s)",
                (research_id, state["user_id"], state["session_id"], Jsonb(candidate)),
            )
        return research_id

    async def link_research(self, research_id, resource_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_research SET resource_id=%s WHERE research_id=%s",
                (resource_id, research_id),
            )

    async def delete_session(self, session_id):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                generation = await (
                    await conn.execute(
                        """UPDATE agent_session_generations SET deleted=true,updated_at=now()
                    WHERE session_id=%s RETURNING *""",
                        (session_id,),
                    )
                ).fetchone()
                if generation:
                    event_id = uuid5(
                        NAMESPACE_URL,
                        f"agent:Session:{session_id}:{generation['generation']}:delete",
                    )
                    await conn.execute(
                        """INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Session',%s,%s,%s,'delete',now(),%s) ON CONFLICT DO NOTHING""",
                        (
                            event_id,
                            session_id,
                            str(generation["user_id"]),
                            generation["generation"],
                            Jsonb(
                                {"session_id": session_id, "generation": generation["generation"]}
                            ),
                        ),
                    )
                await conn.execute(
                    "DELETE FROM agent_execution_records WHERE session_id=%s", (session_id,)
                )
                await conn.execute(
                    "DELETE FROM agent_turn_records WHERE session_id=%s", (session_id,)
                )
                await conn.execute(
                    "DELETE FROM agent_research_budgets WHERE session_id=%s", (session_id,)
                )
                await conn.execute("DELETE FROM agent_research WHERE session_id=%s", (session_id,))
                await conn.execute("DELETE FROM agent_actions WHERE session_id=%s", (session_id,))
                await conn.execute("DELETE FROM agent_threads WHERE session_id=%s", (session_id,))
                await conn.execute("DELETE FROM agent_sessions WHERE session_id=%s", (session_id,))

    async def decision_trace(self, session_id, generation, limit=6):
        """Các lượt gần nhất của phiên cùng các lần gọi tool của chúng, từ nhật ký SQL (mới trước)."""
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    """SELECT t.run_id, t.occurred_at, t.data,
                        COALESCE(json_agg(e.data ORDER BY e.occurred_at)
                                 FILTER (WHERE e.execution_id IS NOT NULL), '[]') AS executions
                    FROM agent_turn_records t
                    LEFT JOIN agent_execution_records e ON e.session_id = t.session_id AND e.run_id = t.run_id
                    WHERE t.session_id=%s AND t.session_generation=%s
                    GROUP BY t.run_id, t.occurred_at, t.data
                    ORDER BY t.occurred_at DESC LIMIT %s""",
                    (session_id, generation, limit),
                )
            ).fetchall()

    async def kg_pending(self, user_id):
        """Số lệnh ghi nghiệp vụ của người dùng chưa được chiếu lên graph (cổng read-your-writes của context graph).

        Chỉ thấy outbox của database này: với database backend tách riêng (KG_BACKEND_DATABASE_URL), sự kiện của
        backend nằm ở database kia và cổng này luôn báo 0."""
        async with self.pool.connection() as conn:
            row = await (
                await conn.execute(
                    """SELECT count(*) AS n FROM kg_outbox
                    WHERE owner_id=%s AND delivered_at IS NULL AND source='backend'""",
                    (str(user_id),),
                )
            ).fetchone()
        return row["n"]

    async def kg_retrieval_gate(self, user_id):
        """Quyền sở hữu/thế hệ SQL hiện tại chặn ngay các episode graph đã cũ."""
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT session_id,generation,deleted FROM agent_session_generations WHERE user_id=%s",
                    (user_id,),
                )
            ).fetchall()
        return {
            "blocked": False,
            "session_generations": {
                r["session_id"]: r["generation"] for r in rows if not r["deleted"]
            },
            "deleted_session_ids": [r["session_id"] for r in rows if r["deleted"]],
        }

    async def record_execution_state(self, state, checkpoint_id=None):
        """Ghi nhật ký các quan sát workflow đã commit và xếp hàng chúng một cách nguyên tử.

        Phát lại một checkpoint không làm gì. Một hành động đã duyệt lần đầu thất bại
        và sau đó thành công tạo ra phiên bản cao hơn của cùng lần thực thi.
        """
        session_id, user_id = state.get("session_id"), state.get("user_id")
        if not session_id or not user_id:
            return
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn, state.get("trace_context"))
                generation = await (
                    await conn.execute(
                        "SELECT * FROM agent_session_generations WHERE session_id=%s FOR UPDATE",
                        (session_id,),
                    )
                ).fetchone()
                if (
                    not generation
                    or generation["deleted"]
                    or str(generation["user_id"]) != user_id
                    or generation["generation"] != state.get("session_generation", 1)
                ):
                    return
                thread = await (
                    await conn.execute(
                        """SELECT kg_checkpoint_id,created_at FROM agent_threads
                    WHERE thread_id=%s AND session_id=%s FOR UPDATE""",
                        (state["run_id"], session_id),
                    )
                ).fetchone()
                if not thread:
                    return
                # ID checkpoint của LangGraph là UUID có thứ tự tăng dần.
                # Bộ đối soát đã đọc checkpoint cũ hơn không được thay
                # một quan sát hành động thành công sau đó bằng một lỗi trước đó.
                if (
                    checkpoint_id
                    and thread["kg_checkpoint_id"]
                    and checkpoint_id <= thread["kg_checkpoint_id"]
                ):
                    await conn.execute(
                        "UPDATE agent_threads SET kg_checked_at=now() WHERE thread_id=%s",
                        (state["run_id"],),
                    )
                    return
                # Gộp các lần thử của cùng một hành động logic trong state này.
                records = {
                    r["execution_id"]: r
                    for r in state.get("execution_records", [])
                    if r.get("execution_id")
                }
                for execution_id, record in records.items():
                    UUID(execution_id)
                    if record.get("status") not in {"succeeded", "failed"}:
                        continue
                    data = {
                        key: record.get(key)
                        for key in (
                            "execution_id",
                            "tool",
                            "status",
                            "duration_ms",
                            "occurred_at",
                            "resource_refs",
                            "error_code",
                            "template_id",
                            "template_version",
                            "args",
                            "outcome",
                        )
                    }
                    data.update(
                        run_id=state["run_id"],
                        session_id=session_id,
                        session_generation=generation["generation"],
                    )
                    row = await (
                        await conn.execute(
                            """INSERT INTO agent_execution_records
                        (execution_id,session_id,session_generation,user_id,run_id,occurred_at,data)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (execution_id) DO UPDATE SET data=EXCLUDED.data,
                        version=agent_execution_records.version+1,occurred_at=EXCLUDED.occurred_at
                        WHERE agent_execution_records.data IS DISTINCT FROM EXCLUDED.data
                        RETURNING version""",
                            (
                                execution_id,
                                session_id,
                                generation["generation"],
                                user_id,
                                state["run_id"],
                                data["occurred_at"],
                                Jsonb(data),
                            ),
                        )
                    ).fetchone()
                    if row:
                        event_id = uuid5(
                            NAMESPACE_URL, f"agent:Execution:{execution_id}:{row['version']}"
                        )
                        await conn.execute(
                            """INSERT INTO kg_outbox
                            (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                            VALUES (%s,'agent','Execution',%s,%s,%s,'upsert',%s,%s) ON CONFLICT DO NOTHING""",
                            (
                                event_id,
                                execution_id,
                                user_id,
                                row["version"],
                                data["occurred_at"],
                                Jsonb(data),
                            ),
                        )
                turn = turn_record(state)
                if turn:
                    turn.update(
                        session_generation=generation["generation"],
                        occurred_at=thread["created_at"].isoformat(),
                    )
                    row = await (
                        await conn.execute(
                            """INSERT INTO agent_turn_records
                        (run_id,session_id,session_generation,user_id,occurred_at,data)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (run_id) DO UPDATE SET data=EXCLUDED.data,version=agent_turn_records.version+1
                        WHERE agent_turn_records.data IS DISTINCT FROM EXCLUDED.data
                        RETURNING version""",
                            (
                                state["run_id"],
                                session_id,
                                generation["generation"],
                                user_id,
                                thread["created_at"],
                                Jsonb(turn),
                            ),
                        )
                    ).fetchone()
                    if row:
                        event_id = uuid5(
                            NAMESPACE_URL, f"agent:Run:{state['run_id']}:{row['version']}"
                        )
                        await conn.execute(
                            """INSERT INTO kg_outbox
                            (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                            VALUES (%s,'agent','Run',%s,%s,%s,'upsert',%s,%s) ON CONFLICT DO NOTHING""",
                            (
                                event_id,
                                state["run_id"],
                                user_id,
                                row["version"],
                                thread["created_at"],
                                Jsonb(turn),
                            ),
                        )
                await conn.execute(
                    "UPDATE agent_threads SET kg_checkpoint_id=COALESCE(%s,kg_checkpoint_id),kg_checked_at=now() WHERE thread_id=%s AND session_id=%s",
                    (checkpoint_id, state["run_id"], session_id),
                )

    async def reconciliation_threads(self, limit=50, grace_seconds=180):
        """Các thread mà lượt chạy cuối có thể đã kết thúc mà không ghi nhật ký (worker sập).

        Lượt chạy tự ghi nhật ký khi hoàn tất; chỉ các thread được đánh dấu và cũ hơn
        thời gian ân hạn mới được đọc, nên hệ thống nhàn rỗi không đọc checkpoint nào.
        """
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    """SELECT thread_id,session_id,kg_checkpoint_id FROM agent_threads
                WHERE needs_reconcile AND last_run_at < now() - make_interval(secs => %s)
                ORDER BY last_run_at LIMIT %s""",
                    (grace_seconds, limit),
                )
            ).fetchall()

    async def checked_thread(self, thread_id):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_threads SET kg_checked_at=now(), needs_reconcile=false WHERE thread_id=%s",
                (thread_id,),
            )

    async def enqueue_kg_snapshot(self):
        """Xếp hàng lại các bản ghi nguồn để dựng lại mà không đổi revision của chúng."""
        count = 0
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await set_psycopg_context(conn)
                rows = await (
                    await conn.execute("""SELECT e.* FROM agent_execution_records e
                    JOIN agent_session_generations g USING(session_id)
                    WHERE NOT g.deleted AND g.generation=e.session_generation""")
                ).fetchall()
                for row in rows:
                    event_id = uuid5(
                        NAMESPACE_URL, f"agent:Execution:{row['execution_id']}:{row['version']}"
                    )
                    await conn.execute(
                        """INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Execution',%s,%s,%s,'upsert',%s,%s)
                        ON CONFLICT (source,aggregate_type,aggregate_id,aggregate_version,operation)
                        DO UPDATE SET delivered_at=NULL,attempts=0,last_error=NULL,available_at=now()""",
                        (
                            event_id,
                            str(row["execution_id"]),
                            str(row["user_id"]),
                            row["version"],
                            row["occurred_at"],
                            Jsonb(row["data"]),
                        ),
                    )
                    count += 1
                turns = await (
                    await conn.execute("""SELECT t.* FROM agent_turn_records t
                    JOIN agent_session_generations g USING(session_id)
                    WHERE NOT g.deleted AND g.generation=t.session_generation""")
                ).fetchall()
                for row in turns:
                    event_id = uuid5(NAMESPACE_URL, f"agent:Run:{row['run_id']}:{row['version']}")
                    await conn.execute(
                        """INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Run',%s,%s,%s,'upsert',%s,%s)
                        ON CONFLICT (source,aggregate_type,aggregate_id,aggregate_version,operation)
                        DO UPDATE SET delivered_at=NULL,attempts=0,last_error=NULL,available_at=now()""",
                        (
                            event_id,
                            row["run_id"],
                            str(row["user_id"]),
                            row["version"],
                            row["occurred_at"],
                            Jsonb(row["data"]),
                        ),
                    )
                    count += 1
                sessions = await (
                    await conn.execute(
                        "SELECT * FROM agent_session_generations WHERE deleted OR generation>1"
                    )
                ).fetchall()
                for row in sessions:
                    generation = row["generation"] if row["deleted"] else row["generation"] - 1
                    event_id = uuid5(
                        NAMESPACE_URL, f"agent:Session:{row['session_id']}:{generation}:delete"
                    )
                    await conn.execute(
                        """INSERT INTO kg_outbox
                        (event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload)
                        VALUES (%s,'agent','Session',%s,%s,%s,'delete',%s,%s)
                        ON CONFLICT (source,aggregate_type,aggregate_id,aggregate_version,operation)
                        DO UPDATE SET delivered_at=NULL,attempts=0,last_error=NULL,available_at=now()""",
                        (
                            event_id,
                            row["session_id"],
                            str(row["user_id"]),
                            generation,
                            row["updated_at"],
                            Jsonb({"session_id": row["session_id"], "generation": generation}),
                        ),
                    )
                    count += 1
        return count

    async def threads(self, session_id):
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT thread_id FROM agent_threads WHERE session_id=%s", (session_id,)
                )
            ).fetchall()
            return [r["thread_id"] for r in rows]

    async def list_sessions(self, user_id, limit=50):
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """SELECT s.session_id, s.thread_id, s.revision, s.created_at, COALESCE(g.generation, 1) AS generation,
                          s.title, s.last_message, s.last_interaction_at, s.message_count, s.last_status
                   FROM agent_sessions s LEFT JOIN agent_session_generations g USING(session_id)
                   WHERE s.user_id=%s ORDER BY COALESCE(s.last_interaction_at, s.created_at) DESC LIMIT %s""",
                    (user_id, limit),
                )
            ).fetchall()
            return rows

    async def deleted_sessions(self, since):
        """Các phiên đã xoá kể từ một thời điểm; bộ nhớ Redis của chúng không được sống lâu hơn chúng."""
        async with self.pool.connection() as conn:
            return await (
                await conn.execute(
                    "SELECT session_id,generation FROM agent_session_generations WHERE deleted AND updated_at>=%s",
                    (since,),
                )
            ).fetchall()
