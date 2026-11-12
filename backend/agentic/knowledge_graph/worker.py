"""Consumer outbox giao dịch của Postgres và các lệnh quản trị.

Chạy từ backend/: python -m agentic.knowledge_graph.worker run
Mọi lệnh đều dùng advisory lock PostgreSQL của backend, kể cả khi database của agent
tách riêng. Một sự kiện chỉ được xác nhận sau khi graph đã commit.
"""

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agentic.observability import metrics, observer, outcome
from agentic.observability.logs import configure_logging
from agentic.observability.persistence import worker_context

from .driver import create_driver, value
from .models import ProjectionEvent
from .projection import MODEL_SOURCES, Projector

log = logging.getLogger(__name__)
LOCK_KEY = "hercfit-knowledge-graph-projection-v1"
EVENT_COLUMNS = "event_id,source,aggregate_type,aggregate_id,owner_id,aggregate_version,operation,occurred_at,payload,trace_context,attempts"


class Worker:
    def __init__(self, settings, *, driver=None):
        self.settings = settings
        self.driver = driver or create_driver(settings)
        self.projector = Projector(self.driver, settings)
        agent_dsn = value(settings, "AGENT_DATABASE_URL")
        backend_dsn = value(settings, "KG_BACKEND_DATABASE_URL") or agent_dsn
        self.dsns = list(dict.fromkeys([backend_dsn, agent_dsn]))
        self.coordinator_dsn = backend_dsn
        self.agent_dsn = agent_dsn
        self._last_trace_heartbeat = 0.0

    @asynccontextmanager
    async def exclusive(self):
        async with await AsyncConnection.connect(
            self.coordinator_dsn, autocommit=True, row_factory=dict_row
        ) as conn:
            row = await (
                await conn.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired", (LOCK_KEY,)
                )
            ).fetchone()
            if not row["acquired"]:
                yield False
                return
            try:
                yield True
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (LOCK_KEY,))

    async def close(self):
        await self.driver.close()
        await observer().close()

    async def consume_once(self):
        async with self.exclusive() as acquired:
            if not acquired:
                return 0
            return await self._consume_locked()

    async def _consume_locked(self):
        count = 0
        batch = value(self.settings, "KG_WORKER_BATCH_SIZE", 100)
        maximum_lag = 0.0
        attempted = 0
        touched = set()
        for dsn in self.dsns:
            async with await AsyncConnection.connect(
                dsn, autocommit=True, row_factory=dict_row
            ) as conn:
                # Thứ tự chỉ ảnh hưởng tính công bằng, không bao giờ ảnh hưởng tính đúng; các bảo vệ
                # phiên bản nguồn của projector chịu được việc commit và giao nhận bị đảo thứ tự.
                events = await (
                    await conn.execute(
                        f"""
                    SELECT {EVENT_COLUMNS} FROM kg_outbox
                    WHERE delivered_at IS NULL AND available_at<=now()
                    ORDER BY occurred_at,event_id LIMIT %s
                """,
                        (batch,),
                    )
                ).fetchall()
                for row in events:
                    attempted += 1
                    event_id = row["event_id"]
                    try:
                        event = ProjectionEvent.model_validate(row)
                        with worker_context(
                            "worker.kg_projection",
                            row.get("trace_context"),
                            event_id=str(event_id),
                            retry_count=row.get("attempts", 0),
                            queue_wait_ms=max(
                                0,
                                (datetime.now(timezone.utc) - row["occurred_at"]).total_seconds()
                                * 1000,
                            ),
                        ):
                            await self.projector.apply(event)
                    except Exception as exc:
                        # Không lưu nội dung exception: lỗi driver có thể
                        # chứa tham số truy vấn nhạy cảm hoặc URL kết nối.
                        await conn.execute(
                            """UPDATE kg_outbox SET attempts=attempts+1,
                            last_error=%s,available_at=now()+make_interval(secs=>LEAST(300,POWER(2,LEAST(attempts+1,8)))::int)
                            WHERE event_id=%s""",
                            (type(exc).__name__, event_id),
                        )
                        log.warning("kg_projection_failed error_type=%s", type(exc).__name__)
                        continue
                    # Sập ở đây sẽ gây giao lại; bảo vệ phiên bản của graph
                    # khiến phép chiếu đã commit trở thành không làm gì.
                    await conn.execute(
                        """UPDATE kg_outbox SET delivered_at=now(),last_error=NULL
                        WHERE event_id=%s""",
                        (event_id,),
                    )
                    count += 1
                    if (
                        event.source == "backend"
                        and event.aggregate_type in MODEL_SOURCES
                        and event.owner_id
                    ):
                        touched.add(event.owner_id)
                lag = await (
                    await conn.execute("""SELECT COALESCE(MAX(EXTRACT(EPOCH FROM (now()-occurred_at))*1000),0) AS lag
                    FROM kg_outbox WHERE delivered_at IS NULL""")
                ).fetchone()
                maximum_lag = max(maximum_lag, float(lag["lag"]))
        await self.refresh_models(touched)
        await self.projector.query(
            """
            MATCH (s:KGState {key:'main'}) SET s.projection_lag_ms=$lag,s.last_poll_at=$time
        """,
            lag=maximum_lag,
            time=datetime.now(timezone.utc).isoformat(),
        )
        if attempted or (maximum_lag > 0 and monotonic() - self._last_trace_heartbeat >= 300):
            self._last_trace_heartbeat = monotonic()
            with worker_context(
                "worker.kg_batch",
                projection_lag_ms=maximum_lag,
                input_count=attempted,
                output_count=count,
            ):
                pass
        log.info("kg_projection_batch delivered=%d projection_lag_ms=%.2f", count, maximum_lag)
        return count

    async def refresh_models(self, owners):
        """Tri thức suy ra dựng lại được: lỗi được ghi log và việc bảo trì sẽ thử lại."""
        refreshed = 0
        for owner in sorted(owners):
            try:
                refreshed += bool(await self.projector.refresh_model(owner))
            except Exception as exc:
                log.warning("kg_model_refresh_failed error_type=%s", type(exc).__name__)
                metrics.incr(
                    "worker_failures_total", worker="kg_model_refresh", error=type(exc).__name__
                )
        return refreshed

    @asynccontextmanager
    async def agent_pool(self):
        async with AsyncConnectionPool(
            self.agent_dsn,
            min_size=1,
            max_size=3,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        ) as pool:
            await pool.open(wait=True)
            yield pool

    async def reconcile(self, limit=50):
        from agentic.services.memory.reconcile import reconcile_checkpoints

        async with self.agent_pool() as pool:
            return await reconcile_checkpoints(pool, limit=limit)

    async def snapshot(self):
        from agentic.services.memory.store import Store

        async with await AsyncConnection.connect(self.coordinator_dsn, autocommit=True) as conn:
            await conn.execute("SELECT kg_enqueue_snapshot()")
        async with self.agent_pool() as pool:
            from agentic.services.memory.reconcile import reconcile_checkpoints

            await reconcile_checkpoints(pool, limit=100000)
            await Store(pool).enqueue_kg_snapshot()

    async def pending(self):
        total = 0
        for dsn in self.dsns:
            async with await AsyncConnection.connect(dsn, autocommit=True) as conn:
                total += (
                    await (
                        await conn.execute(
                            "SELECT count(*) FROM kg_outbox WHERE delivered_at IS NULL"
                        )
                    ).fetchone()
                )[0]
        return total

    async def retry(self):
        for dsn in self.dsns:
            async with await AsyncConnection.connect(dsn, autocommit=True) as conn:
                await conn.execute("""UPDATE kg_outbox SET available_at=now(),last_error=NULL,attempts=0
                    WHERE delivered_at IS NULL AND attempts>0""")

    async def backfill(self, *, rebuild=False):
        async with self.exclusive() as acquired:
            if not acquired:
                raise RuntimeError("Another projection worker is active; retry the command")
            await self.projector.initialize()
            # Trạng thái sẵn sàng chặn truy hồi dở dang trong cả lúc chụp ban đầu
            # lẫn lúc dựng lại. Bia mộ (tombstone) tồn tại trong PostgreSQL, không trong bộ nhớ graph.
            await self.projector.query(
                "MATCH (s:KGState {key:'main'}) SET s.ready=false,s.generation=s.generation+1"
            )
            if rebuild:
                await self.projector.query(
                    "MATCH (n) WHERE n:KGEntity OR n:KGOwner DETACH DELETE n"
                )
            await self.snapshot()
            # Nguồn chụp bao gồm các tombstone có thẩm quyền. Phát lại chúng
            # trước các sự kiện thường, để các lần thực thi cũ đến muộn hay bản ghi riêng tư
            # không khôi phục người dùng hoặc thế hệ phiên đã xoá.
            for dsn in self.dsns:
                async with await AsyncConnection.connect(
                    dsn, autocommit=True, row_factory=dict_row
                ) as conn:
                    rows = await (
                        await conn.execute(f"""SELECT {EVENT_COLUMNS} FROM kg_outbox
                        WHERE operation='delete' AND aggregate_type IN ('User','Session')
                        ORDER BY aggregate_version DESC""")
                    ).fetchall()
                    for row in rows:
                        await self.projector.apply(ProjectionEvent.model_validate(row))
            await self.retry()
            while await self._consume_locked():
                pass
            if await self.pending():
                raise RuntimeError(
                    "Projection backlog contains failures; graph remains warming. Fix errors and rerun backfill."
                )
            await self.projector.prune()
            await self.refresh_models(await self.projector.stale_model_owners(limit=100000))
            await self.projector.query("MATCH (s:KGState {key:'main'}) SET s.ready=true")

    async def listen(self):
        """Một kết nối LISTEN kg_outbox cho mỗi database nguồn (trigger kg_outbox_notify, đánh thức khi commit)."""
        connections = []
        for dsn in self.dsns:
            conn = await AsyncConnection.connect(dsn, autocommit=True)
            await conn.execute("LISTEN kg_outbox")
            connections.append(conn)
        return connections

    @staticmethod
    async def _notified(conn, timeout):
        async for _ in conn.notifies(timeout=timeout, stop_after=1):
            # Một lô ghi có thể sinh nhiều thông báo: gom hết để chỉ chạy một vòng chiếu.
            async for _ in conn.notifies(timeout=0.02):
                pass
            return True
        return False

    async def wait(self, listeners, timeout):
        if not listeners:
            await asyncio.sleep(timeout)
            return
        tasks = [asyncio.create_task(self._notified(conn, timeout)) for conn in listeners]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, *, once=False):
        await self.projector.initialize()
        next_maintenance = 0
        listeners = []
        while True:
            try:
                if not listeners and not once:
                    listeners = await self.listen()
                if monotonic() >= next_maintenance:
                    await self.reconcile()
                    await self.projector.prune()
                    # Các cửa sổ tính theo ngày (7 ngày, tuần này) vẫn dịch chuyển dù không có sự kiện mới.
                    await self.refresh_models(await self.projector.stale_model_owners())
                    next_maintenance = monotonic() + 60
                await self.consume_once()
            except Exception as exc:
                with worker_context("worker.kg_poll_failed"):
                    outcome("failed", error_code=type(exc).__name__)
                log.warning("kg_worker_failed error_type=%s", type(exc).__name__)
                metrics.incr("worker_failures_total", worker="kg_worker", error=type(exc).__name__)
                if once:
                    raise
                for conn in listeners:
                    await conn.close()
                listeners = []  # kết nối lại ở vòng sau; poll vẫn là dự phòng
            if once:
                return
            # Poll định kỳ vẫn chạy: sự kiện đến lại sau backoff không sinh thông báo mới.
            await self.wait(listeners, value(self.settings, "KG_WORKER_POLL_SECONDS", 1))

    async def verify(self, repair=False):
        """So graph với nguồn: phiên bản aggregate (kg_source_versions), cấu trúc (ON_DAY, REFERS_TO) và tổng hợp Day.

        repair: phát lại aggregate lệch từ bảng nguồn và tính lại Day lệch. Dữ liệu thiết bị không có bảng nguồn riêng
        (backend dựng từ health_points), nên chỉ được báo cáo, không phát lại ở đây."""
        from core.graph_outbox import SOURCE_TABLES

        from .projection import DAY_KINDS

        source = {}
        for dsn in self.dsns:
            async with await AsyncConnection.connect(
                dsn, autocommit=True, row_factory=dict_row
            ) as conn:
                pending = {
                    (row["aggregate_type"], row["aggregate_id"])
                    for row in await (
                        await conn.execute(
                            "SELECT aggregate_type, aggregate_id FROM kg_outbox WHERE delivered_at IS NULL"
                        )
                    ).fetchall()
                }
                for row in await (
                    await conn.execute(
                        """SELECT aggregate_type, aggregate_id, version, operation FROM kg_source_versions
                        WHERE source='backend'"""
                    )
                ).fetchall():
                    key = (row["aggregate_type"], row["aggregate_id"])
                    if key not in pending:  # còn sự kiện chưa giao: chưa thể so
                        source[key] = row
        graph = {
            (row["kind"], row["id"]): row
            for row in await self.projector.query(
                """MATCH (n:KGEntity) WHERE n.source='backend' AND n.source_id IS NOT NULL
                RETURN n.kind AS kind, n.source_id AS id, n.source_version AS version, n.deleted AS deleted"""
            )
        }
        stale, visible = [], []
        for key, row in source.items():
            node = graph.get(key)
            if row["operation"] == "upsert" and (
                node is None or (node["version"] or 0) < row["version"]
            ):
                stale.append(key)
            elif row["operation"] == "delete" and node is not None and node["deleted"] is False:
                visible.append(key)
        structure = (
            await self.projector.query(
                """
            CALL () { MATCH (n:KGEntity) WHERE n.kind IN $kinds AND n.deleted = false AND n.local_date IS NOT NULL
                      AND NOT (n)-[:ON_DAY]->(:Day) RETURN count(n) AS unlinked }
            CALL () { MATCH (i:MealItem) WHERE NOT (i)-[:REFERS_TO]->(:Food) RETURN count(i) AS items_without_food }
            CALL () { MATCH (d:Day)
                      OPTIONAL MATCH (m:Meal {owner_id: d.owner_id, local_date: d.date})
                      WHERE m.deleted = false OR m.pruned = true
                      WITH d, count(m) AS meals WHERE meals <> d.meals
                      RETURN collect(d.key) AS days }
            RETURN unlinked, items_without_food, days
        """,
                kinds=list(DAY_KINDS),
            )
        )[0]
        report = {
            "aggregates_checked": len(source),
            "stale_or_missing": len(stale),
            "deleted_but_visible": len(visible),
            "records_without_day": structure["unlinked"],
            "meal_items_without_food": structure["items_without_food"],
            "days_out_of_sync": len(structure["days"]),
        }
        if repair:
            requeued = 0
            async with await AsyncConnection.connect(self.coordinator_dsn, autocommit=True) as conn:
                for kind, ident in stale + visible:
                    if kind in SOURCE_TABLES:
                        await conn.execute(
                            f"SELECT kg_publish_backend(%s, to_jsonb(t)) FROM {SOURCE_TABLES[kind]} t WHERE t.id=%s",
                            (kind, ident),
                        )
                        requeued += 1
            for day_key in structure["days"]:
                _, owner, day = day_key.split(":", 2)
                probe = ProjectionEvent(
                    event_id="00000000-0000-0000-0000-000000000000",
                    source="backend",
                    aggregate_type="Meal",
                    aggregate_id="verify",
                    owner_id=owner,
                    aggregate_version=1,
                    operation="upsert",
                    occurred_at=datetime.now(timezone.utc),
                )
                async with self.driver.session(
                    database=value(self.settings, "NEO4J_DATABASE", "neo4j")
                ) as session:
                    await session.execute_write(
                        self.projector._roll_up, probe, {datetime.fromisoformat(day).date()}
                    )
            report.update(requeued=requeued, days_recomputed=len(structure["days"]))
        return report


async def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["run", "backfill", "rebuild", "retry", "reconcile", "verify"]
    )
    parser.add_argument("--once", action="store_true", help="Process a single batch (run only)")
    parser.add_argument(
        "--confirm-rebuild", action="store_true", help="Acknowledge deletion of derived graph data"
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="verify: requeue drifted aggregates and recompute drifted days",
    )
    options = parser.parse_args(args)
    if options.command == "rebuild" and not options.confirm_rebuild:
        parser.error("rebuild requires --confirm-rebuild; PostgreSQL source records are retained")
    from agentic.core.app.config import AgentSettings

    settings = AgentSettings()
    worker = Worker(settings)
    try:
        if options.command == "run":
            await worker.run(once=options.once)
        elif options.command in {"backfill", "rebuild"}:
            await worker.backfill(rebuild=options.command == "rebuild")
        elif options.command == "retry":
            async with worker.exclusive() as acquired:
                if not acquired:
                    raise RuntimeError("Another projection worker is active; retry the command")
                await worker.retry()
        elif options.command == "verify":
            print(json.dumps(await worker.verify(repair=options.repair), ensure_ascii=False))
        else:
            await worker.reconcile(limit=100000)
    finally:
        await worker.close()


if __name__ == "__main__":
    configure_logging("INFO")
    asyncio.run(main())
