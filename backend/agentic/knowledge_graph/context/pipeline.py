"""f trong G_C = f(G_K, q, u, t, i, s, p): rút đồ thị ngữ cảnh của một câu hỏi.

q câu hỏi · u chủ sở hữu đã xác thực · t khoảng thời gian (timeframe.py) · i ý định, miền và focus của router ·
s trạng thái động (phiên, thế hệ phiên, mốc đồng bộ) · p chính sách (validator.py, giao dịch chỉ đọc, policy.py).

Thứ tự nguồn truy vấn: mẫu viết tay → mẫu đã học theo vân tay → Context Agent sinh mới (tự sửa đúng một lần). Lỗi ở
bất kỳ bước nào trả về một G_C có trạng thái lỗi; bên gọi rơi xuống thẻ tri thức tĩnh rồi tool backend.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter

from neo4j.exceptions import ClientError, Neo4jError

from agentic.observability import annotate

from ..schema import LOCAL
from ..service import normalize
from . import generator, templates, timeframe
from .executor import execute, explain
from .graph import ContextGraph
from .policy import PolicyViolation
from .validator import CypherRejected, validate

log = logging.getLogger(__name__)
FOCUSES = ("summary", "list", "top", "trend", "latest", "relation", "followup")
# Mẫu đã có kế hoạch trong cache chạy vài ms; truy vấn mới sinh còn phải lập kế hoạch (100-700 ms).
TEMPLATE_TIMEOUT = 0.4
GENERATED_TIMEOUT = 1.5
# Chờ worker chiếu lệnh ghi vừa xong (LISTEN/NOTIFY: thường dưới 100 ms) trước khi trả lời từ graph.
SYNC_WAIT = 0.3
SYNC_POLL = 0.05
# Giá trị canh: danh sách/map rỗng đổi kiểu tham số và làm Neo4j lập lại kế hoạch; giá trị này không khớp gì.
SENTINEL = "\x00"


async def synced(store, owner):
    if store is None or not hasattr(store, "kg_pending"):
        return True
    deadline = perf_counter() + SYNC_WAIT
    while True:
        if not await store.kg_pending(owner):
            return True
        if perf_counter() >= deadline:
            return False
        await asyncio.sleep(SYNC_POLL)


def parameters(owner, frame, terms, session_id, sessions, now):
    """Giá trị của u, t, s: luôn do code gán, không bao giờ do model viết."""
    return {
        "owner": owner,
        "start": frame.start,
        "end": frame.end,
        "today": now.astimezone(LOCAL).date(),
        "now": now,
        "grain": frame.grain,
        "terms": terms or [SENTINEL],
        "session_id": session_id or SENTINEL,
        "session_ids": list(sessions) or [SENTINEL],
        "generations": sessions or {SENTINEL: 0},
    }


def _error(exc):
    if isinstance(exc, CypherRejected):
        return "rejected:" + exc.code
    if isinstance(exc, PolicyViolation):
        return "policy:" + exc.code
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ClientError):
        code = exc.code or ""
        return "timeout" if "TransactionTimedOut" in code or "Timeout" in code else "cypher_error"
    if isinstance(exc, Neo4jError):
        return "neo4j_error"
    return "unavailable"


async def build(
    service, models, *, owner, session_id, question, decision, now=None, generate=True, seeds=True
):
    """`seeds=False` bỏ qua mọi mẫu đã có, cả seed lẫn mẫu đã học, và không lưu truy vấn sinh ra (chỉ để đo riêng
    text-to-Cypher trong kg_eval: truy vấn của một model đang thử không được thành mẫu cho người dùng thật)."""
    started = perf_counter()
    need = decision.get("context") or {}
    focus = need.get("focus") if need.get("focus") in FOCUSES else "summary"
    domain, intent = decision.get("domain"), decision.get("intent")
    now = now or datetime.now(timezone.utc)
    frame = timeframe.resolve(
        question, now.astimezone(LOCAL).date(), need.get("start"), need.get("end"), focus
    )
    terms = [
        t for t in dict.fromkeys(normalize(str(e)).strip() for e in need.get("entities") or []) if t
    ][:5]
    graph = ContextGraph(timeframe=frame.as_dict(), status="unavailable")
    pool = getattr(service.store, "pool", None)
    key = templates.fingerprint(intent, domain, focus, frame.grain, bool(terms))
    try:
        gate = await service.store.kg_retrieval_gate(owner) if service.store is not None else {}
        if gate.get("blocked"):
            graph.status = "blocked"
            return graph
        deleted = set(gate.get("deleted_session_ids", []))
        sessions = {
            str(k): int(v)
            for k, v in gate.get("session_generations", {}).items()
            if str(k) not in deleted
        }
        graph.synced = await synced(service.store, owner)
        params = parameters(owner, frame, terms, session_id, sessions, now)
        seed = templates.seed_for(domain, focus, frame.grain, bool(terms)) if seeds else None
        if seed is not None:
            plan = [("seed", seed.id, seed.cypher)]
        else:
            row = await templates.learned(pool, key) if seeds else None
            plan = [("learned", key, row["cypher"])] if row else []
        if not plan and generate and models is not None:
            plan = [("generated", key, None)]
        rejected = None
        while plan:
            source, template, text = plan.pop(0)
            graph.attempts += 1
            try:
                if text is None:
                    text = await generator.generate(
                        models,
                        question=question,
                        intent=intent,
                        domain=domain,
                        focus=focus,
                        frame=frame,
                        terms=terms,
                        rejected=rejected,
                    )
                checked = validate(text)
                if source == "generated":
                    await explain(service, checked.cypher, params)
                columns, rows, nodes, edges = await execute(
                    service,
                    checked.cypher,
                    params,
                    owner=owner,
                    sessions=sessions,
                    timeout=GENERATED_TIMEOUT if source == "generated" else TEMPLATE_TIMEOUT,
                )
            except Exception as exc:
                graph.error = _error(exc)
                log.warning("context_graph_failed source=%s error=%s", source, graph.error)
                if source == "learned":
                    await templates.record(pool, key, False, graph.error)
                repairable = (
                    isinstance(exc, (CypherRejected, ClientError)) and graph.error != "timeout"
                )
                if source == "learned" and generate and models is not None:
                    plan.append(("generated", key, None))
                elif source == "generated" and repairable and rejected is None and text:
                    rejected = (text, str(exc)[:400])
                    plan.append(("generated", key, None))
                graph.status = (
                    "timeout"
                    if graph.error == "timeout"
                    else (
                        "rejected"
                        if graph.error.startswith(("rejected", "policy", "cypher"))
                        else "unavailable"
                    )
                )
                continue
            graph.source, graph.template, graph.fingerprint = source, template, key
            graph.columns, graph.rows, graph.nodes, graph.edges = columns, rows, nodes, edges
            graph.status, graph.error, graph.cypher = (
                ("ok" if rows else "empty"),
                None,
                checked.cypher,
            )
            if source == "generated" and seeds:
                await templates.remember(pool, key, text)
            elif source == "learned":
                await templates.record(pool, key, True)
            break
        if not graph.attempts:
            graph.status = "skipped"
    # Gate hay Neo4j không truy cập được: lượt chạy tiếp bằng thẻ tĩnh/backend.
    except Exception as exc:
        graph.status, graph.error = "unavailable", _error(exc)
        log.warning("context_graph_unavailable error=%s", graph.error)
    finally:
        graph.duration_ms = round((perf_counter() - started) * 1000, 1)
        annotate(
            context_status=graph.status,
            context_source=graph.source,
            context_template=graph.template,
            context_rows=len(graph.rows),
            context_synced=graph.synced,
            context_ms=graph.duration_ms,
        )
    return graph


async def warm_templates(service):
    """Chạy mọi mẫu seed và mẫu đã học với tham số cùng kiểu với lượt thật, để kế hoạch nằm sẵn trong cache."""
    now = datetime.now(timezone.utc)
    today = now.astimezone(LOCAL).date()
    frame = timeframe.TimeFrame(today - timedelta(days=6), today, "day", "default")
    params = parameters("kg-warm-up", frame, ["warm"], "kg-warm-up", {"kg-warm-up": 1}, now)
    texts = [seed.cypher for seed in templates.SEEDS]
    texts += await templates.warm_list(getattr(service.store, "pool", None))
    for text in texts:
        try:
            await execute(
                service,
                validate(text).cypher,
                params,
                owner="kg-warm-up",
                sessions={},
                timeout=GENERATED_TIMEOUT,
            )
        except Exception as exc:
            log.warning("context_graph_warm_failed error=%s", _error(exc))
