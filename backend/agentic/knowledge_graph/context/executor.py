"""Chạy Cypher đã qua validator: transaction chỉ đọc (lớp chính sách thứ hai), timeout phía server, giới hạn hàng."""

import asyncio

from neo4j import READ_ACCESS, Query

from ..driver import create_driver, value
from .policy import plain
from .validator import CypherRejected

MAX_ROWS = 50
# Lập kế hoạch là phần đắt nhất của một truy vấn mới (đo: 140-730 ms); kế hoạch đã cache thì vài ms.
EXPLAIN_TIMEOUT = 2.0


def _driver(service):
    if service.driver is None:
        service.driver = create_driver(service.settings)
    return service.driver


def _session(service):
    # Không ghi thông báo của server vào log: "property does not exist" là bình thường khi chưa có dữ liệu thiết bị.
    return _driver(service).session(
        database=value(service.settings, "NEO4J_DATABASE", "neo4j"),
        default_access_mode=READ_ACCESS,
        notifications_min_severity="OFF",
    )


def _operators(plan):
    if not plan:
        return []
    found = [plan.get("operatorType", "")]
    for child in plan.get("children") or []:
        found += _operators(child)
    return found


async def explain(service, cypher, params):
    """Neo4j phân tích và lập kế hoạch truy vấn mà không chạy: bắt lỗi cú pháp/ngữ nghĩa trước lần chạy thật."""

    async def plan():
        async with _session(service) as session:
            result = await session.run(Query("EXPLAIN " + cypher, timeout=EXPLAIN_TIMEOUT), params)
            return (await result.consume()).plan

    operators = _operators(await asyncio.wait_for(plan(), EXPLAIN_TIMEOUT + 0.5))
    if any(op.startswith("AllNodesScan") for op in operators):
        raise CypherRejected("all_nodes_scan", "truy vấn quét toàn bộ graph")
    return operators


async def execute(service, cypher, params, *, owner, sessions, timeout):
    """(cột, hàng, số nút, số cạnh). Giá trị đã qua policy.plain: nút lạ hay đã xoá làm hỏng cả kết quả."""

    async def fetch():
        async with _session(service) as session:
            result = await session.run(Query(cypher, timeout=timeout), params)
            keys = list(result.keys())
            records = []
            async for record in result:
                records.append(record)
                if len(records) >= MAX_ROWS:
                    break
            await result.consume()
            return keys, records

    keys, records = await asyncio.wait_for(fetch(), timeout + 0.5)
    stats = {"nodes": set(), "edges": set()}
    rows = [[plain(item, owner, sessions, stats) for item in record.values()] for record in records]
    return keys, rows, len(stats["nodes"]), len(stats["edges"])
