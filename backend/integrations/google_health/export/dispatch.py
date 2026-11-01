"""GH_EXPORT_DISPATCH: gửi các thay đổi đã ghi nhận lên Google, không bao giờ hai lần và không bao giờ mù quáng.

Trạng thái (export_outbox.state):
  PENDING -> DISPATCHING -> CONFIRMED            Operation đã xong, hoặc lần đọc lại khớp
  DISPATCHING -> VERIFYING (timeout / 5xx / chưa xong): đọc lại trước mọi việc khác
  VERIFYING -> CONFIRMED (Google đang giữ một data point HercFit ghi với nội dung này)
            -> PENDING (đã chứng minh vắng mặt: gửi lại) | UNCERTAIN (không kiểm tra được: dừng thử lại mù)
  Google tự cấp id cho data point và bỏ qua tên do client đặt (đã kiểm tra bằng tài khoản
  thật ngày 2026-11-01 với weight, nutrition-log và exercise), nên một lệnh tạo bị mất được tìm bằng cách
  liệt kê các ngày của bản ghi và so khớp nội dung do OAuth client của chúng ta ghi.
  bất kỳ -> BLOCKED_PERMISSION (thiếu scope ghi; lệnh đọc vẫn chạy), FAILED (400),
           SUPERSEDED (đang có phiên bản mới hơn của cùng bản ghi chờ gửi)
  UPDATE/DELETE chỉ chạm tới các data point HercFit đã tạo (mapping được sở hữu). Nếu data point
  đã đổi trên Google kể từ lần ghi cuối của chúng ta, dòng trở thành CONFLICT và một
  mục export_conflicts chờ người dùng (giữ bản cục bộ / nhận bản từ xa).

Lệnh ghi chỉ chạy khi công tắc ngắt khẩn cấp bật (GH_EXPORT_DISPATCH), nhóm được phép
(GH_EXPORT_GROUPS) và khả năng đã kiểm chứng bằng tài khoản thật
(GOOGLE_HEALTH_VERIFIED_CAPABILITIES, ví dụ "weight:create").
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from core.database import get_db_session
from core.jobs import queue
from core.settings import settings
from domains.shared.models.basemodel import uuid7
from integrations.google_health.adapters import adapter
from integrations.google_health.client import PERMISSION, SCHEMA, UNSUPPORTED, GoogleHealthError
from integrations.google_health.contract import scopes as contract_scopes
from integrations.google_health.contract.registry import Op, runtime_enabled, spec
from integrations.google_health.export import selfsource
from integrations.google_health.ingest import reads
from integrations.google_health.ingest.jobs import Context, _client, _connection, fenced

MAX_ROWS = 50
MAX_VERIFY = 3
OP_CAPABILITY = {"CREATE": Op.CREATE, "UPDATE": Op.PATCH, "DELETE": Op.BATCH_DELETE}


def _shape(data_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return adapter().parse_point(data_type, payload).value


def _restrict(value: Any, shape: Any) -> Any:
    """Phần giá trị do HercFit ghi: Google tự thêm các trường của nó (ví dụ sampleTime.civilTime)."""
    if isinstance(shape, dict):
        source = value if isinstance(value, dict) else {}
        return {key: _restrict(source.get(key), item) for key, item in shape.items()}
    return value


def _typed(data_type: str, point: dict[str, Any], shape: dict[str, Any] | None = None) -> str:
    """Băm của giá trị có kiểu (qua adapter schema); với `shape` thì chỉ các trường HercFit đã ghi."""
    value = adapter().parse_point(data_type, point).value
    if shape is not None:
        value = _restrict(value, shape)
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def _next_row(session, connection_id) -> dict[str, Any] | None:
    row = (await session.execute(text("""
        SELECT o.*, m.id AS mapping_id, m.remote_name, m.client_id, m.remote_sha256, m.owned_by_hercfit
        FROM export_outbox o
        LEFT JOIN google_resource_mappings m ON m.connection_id = o.connection_id AND m.aggregate_type = o.aggregate_type
             AND m.aggregate_id = o.aggregate_id AND m.data_type = o.data_type
        WHERE o.connection_id = :c AND o.state IN ('PENDING', 'VERIFYING') AND o.available_at <= now()
        ORDER BY o.created_at LIMIT 1 FOR UPDATE OF o SKIP LOCKED"""), {"c": connection_id})).mappings().first()
    return dict(row) if row else None


async def _set(session, row: dict[str, Any], state: str, *, error: str | None = None, delay: timedelta | None = None,
               remote_name: str | None = None, operation: dict | None = None) -> None:
    await session.execute(text("""
        UPDATE export_outbox SET state = CAST(:state AS varchar), last_error = CAST(:error AS varchar), updated_at = now(),
               available_at = now() + make_interval(secs => :delay),
               remote_name = COALESCE(CAST(:remote AS varchar), remote_name),
               google_operation = COALESCE(CAST(:operation AS jsonb), google_operation),
               confirmed_at = CASE WHEN CAST(:state AS varchar) = 'CONFIRMED' THEN now() ELSE confirmed_at END
        WHERE id = :id"""), {"id": row["id"], "state": state, "error": (error or "")[:120] or None,
                             "delay": (delay or timedelta(0)).total_seconds(), "remote": remote_name,
                             "operation": json.dumps(operation) if operation is not None else None})


async def _confirm_mapping(session, row: dict[str, Any], remote_name: str | None, *, deleted: bool = False) -> None:
    await session.execute(text("""
        UPDATE google_resource_mappings SET remote_name = COALESCE(CAST(:remote AS varchar), remote_name),
               state = CAST(:state AS varchar),
               local_version = :version, payload_sha256 = :sha, remote_sha256 = :remote_sha, updated_at = now()
        WHERE id = :id"""), {"id": row["mapping_id"], "remote": remote_name, "version": row["aggregate_version"],
                             "state": "DELETED" if deleted else "CONFIRMED", "sha": row["payload_sha256"],
                             "remote_sha": _typed(row["data_type"], row["payload"])})


def _blocked(row: dict[str, Any], connection) -> str | None:
    if not settings.GH_EXPORT_DISPATCH:
        return "dispatch_disabled"
    if row["export_group"] not in settings.GH_EXPORT_GROUPS:
        return "group_not_rolled_out"
    capability = OP_CAPABILITY[row["op"]]
    if not runtime_enabled(row["data_type"], capability, verified=settings.verified_capabilities):
        return "capability_unverified"
    if not contract_scopes.can_write(spec(row["data_type"]).scope_group, connection.granted_scopes or []):
        return "write_scope_missing"
    return None


async def dispatch(ctx: Context) -> None:
    job = ctx.job
    async with get_db_session() as session:
        connection = await _connection(session, job)
    client = await _client(ctx, connection)
    done: dict[str, int] = {}
    for _ in range(MAX_ROWS):
        async with fenced(job) as session:
            row = await _next_row(session, connection.id)
            if row is None:
                break
            reason = _blocked(row, connection)
            if reason:
                state = "BLOCKED_PERMISSION" if reason == "write_scope_missing" else "PENDING"
                await _set(session, row, state, error=reason, delay=timedelta(hours=1))
                done[state] = done.get(state, 0) + 1
                continue
            # Một phiên bản mới hơn đang chờ của cùng bản ghi thay cho dòng này.
            newer = (await session.execute(text("""
                SELECT 1 FROM export_outbox WHERE aggregate_type = :t AND aggregate_id = :a AND data_type = :d
                  AND aggregate_version > :v AND state = 'PENDING' LIMIT 1"""),
                {"t": row["aggregate_type"], "a": row["aggregate_id"], "d": row["data_type"],
                 "v": row["aggregate_version"]})).first()
            if newer and row["state"] == "PENDING":
                await _set(session, row, "SUPERSEDED")
                done["SUPERSEDED"] = done.get("SUPERSEDED", 0) + 1
                continue
            verifying = row["state"] == "VERIFYING"
            await session.execute(text("UPDATE export_outbox SET state = 'DISPATCHING', attempts = attempts + 1 "
                                       "WHERE id = :id"), {"id": row["id"]})
        outcome = await (_verify(client, row) if verifying else _send(client, row))
        async with fenced(job) as session:
            await _record(session, row, outcome)
        done[outcome["state"]] = done.get(outcome["state"], 0) + 1
    async with fenced(job) as session:
        pending = (await session.execute(text(
            "SELECT 1 FROM export_outbox WHERE connection_id = :c AND state IN ('PENDING', 'VERIFYING') "
            "AND available_at <= now() LIMIT 1"), {"c": connection.id})).first()
        if pending:
            await queue.requeue(session, job, {"result": done})
        else:
            await queue.complete(session, job, done)


async def _send(client, row: dict[str, Any]) -> dict[str, Any]:
    data_type, payload, op = row["data_type"], row["payload"], row["op"]
    try:
        if op == "CREATE":
            # Client không bao giờ thử lại: Google tự cấp id, nên POST lần hai có thể thành data point thứ hai.
            return _from_operation(await client.create_point(data_type, payload), row, fallback_name=None)
        if not row.get("owned_by_hercfit") or not row.get("remote_name"):
            return {"state": "UNCERTAIN", "error": "no_owned_remote_point"}
        if op == "UPDATE":
            remote = await client.get_point(row["remote_name"])
            if row.get("remote_sha256") and _typed(data_type, remote, _shape(data_type, payload)) != row["remote_sha256"]:
                return {"state": "CONFLICT", "remote": remote}
            return _from_operation(await client.patch_point(row["remote_name"], payload), row,
                                   fallback_name=row["remote_name"])
        operation = await client.batch_delete(data_type, [row["remote_name"]])
        return {**_from_operation(operation, row, fallback_name=row["remote_name"]), "deleted": True}
    except GoogleHealthError as exc:
        if exc.error_class == PERMISSION:
            return {"state": "BLOCKED_PERMISSION", "error": exc.code}
        if exc.error_class in (SCHEMA, UNSUPPORTED):
            return {"state": "FAILED", "error": exc.code}
        return {"state": "VERIFYING", "error": exc.code}  # kết quả chưa rõ: không bao giờ gửi lại mù quáng


def _from_operation(operation: dict[str, Any], row: dict[str, Any], *, fallback_name: str | None) -> dict[str, Any]:
    if operation.get("error"):
        return {"state": "FAILED", "error": str((operation["error"] or {}).get("code"))[:40], "operation": operation}
    if operation.get("done"):
        response = operation.get("response") or {}
        return {"state": "CONFIRMED", "remote_name": response.get("name") or fallback_name, "operation": operation}
    return {"state": "VERIFYING", "error": "operation_pending", "operation": operation,
            "remote_name": fallback_name}


async def _verify(client, row: dict[str, Any]) -> dict[str, Any]:
    """Đọc lại một kết quả chưa rõ: theo id của Google khi đã biết, nếu không thì theo nội dung."""
    data_type, payload = row["data_type"], row["payload"]
    name = row.get("remote_name")
    if name is None:
        if row["op"] != "CREATE":
            return {"state": "UNCERTAIN", "error": "no_remote_name"}
        try:
            found = await _find_written(client, row)
        except GoogleHealthError as exc:
            return {"state": "VERIFYING", "error": exc.code}
        except _Unsearchable:
            return {"state": "UNCERTAIN", "error": "not_searchable"}
        if found is None:
            return _absent(row)
        return {"state": "CONFIRMED", "remote_name": found}
    try:
        remote = await client.get_point(name)
    except GoogleHealthError as exc:
        if exc.error_class == UNSUPPORTED:  # 404: đã chứng minh là vắng mặt
            return _absent(row)
        return {"state": "VERIFYING", "error": exc.code}
    if row["op"] == "DELETE":
        return {"state": "VERIFYING", "error": "still_present"}
    same = _typed(data_type, remote, _shape(data_type, payload)) == _typed(data_type, payload)
    return {"state": "CONFIRMED" if same else "CONFLICT", "remote_name": name, "remote": remote}


def _absent(row: dict[str, Any]) -> dict[str, Any]:
    if row["op"] == "CREATE" and row["attempts"] < MAX_VERIFY:
        return {"state": "PENDING", "error": "absent_resend"}  # đã chứng minh vắng mặt, nên gửi lại không thể tạo bản trùng
    return {"state": "UNCERTAIN", "error": "absent"}


class _Unsearchable(Exception):
    """Data point không mang thời điểm nào mà filter của lệnh list tìm được."""


async def _find_written(client, row: dict[str, Any]) -> str | None:
    """Tên Google của data point do OAuth client của chúng ta ghi với nội dung này, tìm qua danh sách các ngày của nó."""
    data_type, payload = row["data_type"], row["payload"]
    parsed = adapter().parse_point(data_type, payload)
    start = parsed.time.physical_start
    if start is None:
        raise _Unsearchable
    day = (start + timedelta(seconds=parsed.time.start_offset_s or 0)).date()
    plan = reads.plan(data_type, rollup=False)
    query = reads.list_filter(plan, day - timedelta(days=1), day + timedelta(days=2))  # giấc ngủ được xếp vào ngày kết thúc của nó
    fetch = await client.list_all(data_type, filter=query, page_size=plan.page_size, max_pages=5)
    expected, shape = _typed(data_type, payload), parsed.value
    for point in fetch.points:
        if selfsource.written_by_us(point.get("dataSource")) and _typed(data_type, point, shape) == expected:
            return point.get("name")
    if not fetch.complete:
        raise GoogleHealthError("verify_page_budget")
    return None


async def _record(session, row: dict[str, Any], outcome: dict[str, Any]) -> None:
    state = outcome["state"]
    if state == "VERIFYING" and row["attempts"] + 1 >= MAX_VERIFY + 1:
        state = "UNCERTAIN"
    delay = {"VERIFYING": timedelta(minutes=2), "PENDING": timedelta(seconds=30)}.get(state)
    await _set(session, row, state, error=outcome.get("error"), delay=delay, remote_name=outcome.get("remote_name"),
               operation=outcome.get("operation"))
    if state == "CONFIRMED":
        await _confirm_mapping(session, row, outcome.get("remote_name"), deleted=bool(outcome.get("deleted")))
    elif state == "CONFLICT":
        await session.execute(text("UPDATE google_resource_mappings SET state = 'CONFLICT', updated_at = now() "
                                   "WHERE id = :id"), {"id": row["mapping_id"]})
        await session.execute(text("""
            INSERT INTO export_conflicts (id, user_id, mapping_id, outbox_id, local_payload, remote_payload)
            VALUES (:id, :u, :m, :o, CAST(:local AS jsonb), CAST(:remote AS jsonb))"""),
            {"id": uuid7(), "u": row["user_id"], "m": row["mapping_id"], "o": row["id"],
             "local": json.dumps(row["payload"]), "remote": json.dumps(outcome.get("remote"))})
    elif state == "UNCERTAIN":
        await session.execute(text("UPDATE google_resource_mappings SET state = 'UNCERTAIN', updated_at = now() "
                                   "WHERE id = :id"), {"id": row["mapping_id"]})


HANDLERS = {"GH_EXPORT_DISPATCH": dispatch}
