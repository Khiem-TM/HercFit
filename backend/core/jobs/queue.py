"""Job: xếp hàng, lấy, heartbeat và kết thúc, tất cả đều được fence bằng lease epoch của job.

Mỗi lần lấy job đều tăng `lease_epoch`. Worker đã mất lease (sập, tạm dừng,
hết hạn) có thể vẫn đang chạy; mọi lệnh ghi của nó đều qua `fence(job)`,
hàm này khoá dòng job và kiểm tra epoch, nên worker cũ không thể hoàn tất,
lên lịch lại hay ghi kết quả cho một job mà người khác đang sở hữu.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from domains.shared.models.basemodel import uuid7

ACTIVE_STATES = ("QUEUED", "RETRY", "RUNNING")
DEFAULT_LEASE = timedelta(seconds=120)


class JobFenced(Exception):
    """Lease của job đã chuyển đi (hoặc job đã xong): worker này phải ngừng ghi."""


@dataclass
class Job:
    id: UUID
    kind: str
    queue: str
    user_id: UUID | None
    connection_id: UUID | None
    data_type: str | None
    window_start: date | None
    window_end: date | None
    payload: dict[str, Any]
    progress: dict[str, Any]
    attempts: int
    max_attempts: int
    lease_epoch: int
    connection_generation: int | None
    root_id: UUID | None
    operation_id: UUID | None
    parent_id: UUID | None = None
    priority: int = 50
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row) -> Job:
        data = dict(row._mapping)
        return cls(**{name: data.get(name) for name in (
            "id", "kind", "queue", "user_id", "connection_id", "data_type", "window_start", "window_end", "payload",
            "progress", "attempts", "max_attempts", "lease_epoch", "connection_generation", "root_id",
            "operation_id", "parent_id", "priority")})


async def enqueue(session, kind: str, *, queue: str = "ingest", dedupe_key: str | None = None,
                  user_id: UUID | None = None, connection_id: UUID | None = None, data_type: str | None = None,
                  window_start: date | None = None, window_end: date | None = None,
                  payload: dict[str, Any] | None = None, progress: dict[str, Any] | None = None, priority: int = 50,
                  run_after: datetime | None = None, connection_generation: int | None = None,
                  parent_id: UUID | None = None, root_id: UUID | None = None, operation_id: UUID | None = None,
                  max_attempts: int = 8) -> UUID | None:
    """Chèn một job trong transaction của bên gọi; None khi đã có job tương đương (dedupe key) đang chờ."""
    job_id = uuid7()
    async with session.begin_nested():
        row = (await session.execute(text("""
            INSERT INTO jobs (id, kind, queue, dedupe_key, user_id, connection_id, data_type, window_start, window_end,
                              payload, progress, priority, run_after, connection_generation, parent_id, root_id,
                              operation_id, max_attempts)
            VALUES (:id, :kind, :queue, :dedupe_key, :user_id, :connection_id, :data_type, :window_start, :window_end,
                    CAST(:payload AS jsonb), CAST(:progress AS jsonb), :priority, COALESCE(:run_after, now()),
                    :generation, :parent_id, COALESCE(:root_id, :id), :operation_id, :max_attempts)
            ON CONFLICT (kind, dedupe_key) WHERE dedupe_key IS NOT NULL AND state IN ('QUEUED', 'RETRY', 'RUNNING')
            DO NOTHING RETURNING id"""), {
            "id": job_id, "kind": kind, "queue": queue, "dedupe_key": dedupe_key, "user_id": user_id,
            "connection_id": connection_id, "data_type": data_type, "window_start": window_start,
            "window_end": window_end, "payload": json.dumps(payload or {}, default=str),
            "progress": json.dumps(progress or {}, default=str), "priority": priority, "run_after": run_after,
            "generation": connection_generation, "parent_id": parent_id, "root_id": root_id,
            "operation_id": operation_id, "max_attempts": max_attempts})).first()
    if operation_id:
        target = row[0] if row else (await session.execute(text(
            "SELECT id FROM jobs WHERE kind = :kind AND dedupe_key = :key "
            "ORDER BY created_at DESC, id DESC LIMIT 1"), {"kind": kind, "key": dedupe_key})).scalar()
        if target:
            await session.execute(text("INSERT INTO operation_jobs (operation_id, job_id) VALUES (:o, :j) "
                                       "ON CONFLICT DO NOTHING"), {"o": operation_id, "j": target})
    return row[0] if row else None


async def claim(session, queues: tuple[str, ...], owner: str, *, lease: timedelta = DEFAULT_LEASE) -> Job | None:
    """Lease job sẵn sàng khẩn cấp nhất; mỗi (kết nối, loại dữ liệu) chỉ một job nhập RUNNING."""
    try:
        async with session.begin_nested():
            row = (await session.execute(text("""
                UPDATE jobs SET state = 'RUNNING', lease_owner = :owner, lease_epoch = lease_epoch + 1,
                       lease_until = now() + make_interval(secs => :lease), heartbeat_at = now(),
                       attempts = attempts + 1, started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = (
                    SELECT j.id FROM jobs j
                    WHERE j.queue = ANY(:queues) AND j.state IN ('QUEUED', 'RETRY') AND j.run_after <= now()
                      AND NOT EXISTS (SELECT 1 FROM jobs r WHERE r.state = 'RUNNING' AND r.queue = 'ingest'
                                      AND j.queue = 'ingest' AND r.connection_id = j.connection_id
                                      AND r.data_type = j.data_type)
                      AND NOT EXISTS (SELECT 1 FROM jobs r WHERE r.state = 'RUNNING'
                                      AND r.kind = 'GH_EXPORT_DISPATCH' AND j.kind = 'GH_EXPORT_DISPATCH'
                                      AND r.connection_id = j.connection_id)
                    ORDER BY j.priority DESC, j.run_after, j.id
                    LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING *"""), {"queues": list(queues), "owner": owner[:80], "lease": lease.total_seconds()})).first()
    except IntegrityError:  # thua một cuộc đua trên uq_jobs_running_type; thử lại ở tick sau
        return None
    return Job.from_row(row) if row else None


async def fence(session, job: Job) -> None:
    """Khoá dòng job và chứng minh worker này vẫn sở hữu nó; gọi đầu tiên trong mọi transaction ghi."""
    row = (await session.execute(text(
        "SELECT 1 FROM jobs WHERE id = :id AND lease_epoch = :epoch AND state = 'RUNNING' FOR UPDATE"),
        {"id": job.id, "epoch": job.lease_epoch})).first()
    if row is None:
        raise JobFenced(str(job.id))


async def heartbeat(session, job: Job, *, lease: timedelta = DEFAULT_LEASE) -> bool:
    row = (await session.execute(text("""
        UPDATE jobs SET lease_until = now() + make_interval(secs => :lease), heartbeat_at = now()
        WHERE id = :id AND lease_epoch = :epoch AND state = 'RUNNING' RETURNING 1"""),
        {"id": job.id, "epoch": job.lease_epoch, "lease": lease.total_seconds()})).first()
    return row is not None


async def save_progress(session, job: Job, progress: dict[str, Any]) -> None:
    await fence(session, job)
    job.progress = progress
    await session.execute(text("UPDATE jobs SET progress = CAST(:progress AS jsonb), updated_at = now() WHERE id = :id"),
                          {"id": job.id, "progress": json.dumps(progress, default=str)})


async def _finish(session, job: Job, state: str, *, error_class: str | None = None, error_code: str | None = None,
                  run_after: datetime | None = None, result: dict[str, Any] | None = None) -> None:
    await fence(session, job)
    await session.execute(text("""
        UPDATE jobs SET state = CAST(:state AS varchar), error_class = CAST(:error_class AS varchar),
               error_code = CAST(:error_code AS varchar), lease_owner = NULL,
               lease_until = NULL, run_after = COALESCE(CAST(:run_after AS timestamptz), run_after), updated_at = now(),
               finished_at = CASE WHEN CAST(:state AS varchar) IN ('SUCCEEDED', 'NEEDS_ATTENTION', 'CANCELLED')
                                  THEN now() END,
               progress = CASE WHEN CAST(:result AS jsonb) IS NULL THEN progress
                               ELSE progress || jsonb_build_object('result', CAST(:result AS jsonb)) END
        WHERE id = :id"""), {"id": job.id, "state": state, "error_class": error_class,
                             "error_code": (error_code or "")[:64] or None, "run_after": run_after,
                             "result": json.dumps(result, default=str) if result is not None else None})


async def complete(session, job: Job, result: dict[str, Any] | None = None) -> None:
    await _finish(session, job, "SUCCEEDED", result=result)


async def retry(session, job: Job, *, delay: timedelta, error_class: str, error_code: str) -> None:
    when = (await session.execute(text("SELECT now() + make_interval(secs => :delay)"),
                                  {"delay": delay.total_seconds()})).scalar_one()
    await _finish(session, job, "RETRY", error_class=error_class, error_code=error_code, run_after=when)


async def needs_attention(session, job: Job, *, error_class: str, error_code: str) -> None:
    await _finish(session, job, "NEEDS_ATTENTION", error_class=error_class, error_code=error_code)


async def cancel(session, job: Job, reason: str) -> None:
    await _finish(session, job, "CANCELLED", error_class="CANCELLED", error_code=reason)


async def reap(session) -> int:
    """Lease hết hạn quay về RETRY; lần lấy sau tăng epoch và fence worker cũ."""
    result = await session.execute(text("""
        UPDATE jobs SET state = CASE WHEN attempts >= max_attempts THEN 'NEEDS_ATTENTION' ELSE 'RETRY' END,
               error_class = COALESCE(error_class, 'TRANSIENT'), error_code = 'lease_expired',
               lease_owner = NULL, lease_until = NULL, updated_at = now(),
               finished_at = CASE WHEN attempts >= max_attempts THEN now() END
        WHERE state = 'RUNNING' AND lease_until < now()"""))
    return result.rowcount or 0


async def cancel_for_connection(session, connection_id: UUID, reason: str) -> int:
    """Ngắt kết nối: các job đang chờ của kết nối bị huỷ (job đang chạy bị fence theo thế hệ)."""
    result = await session.execute(text("""
        UPDATE jobs SET state = 'CANCELLED', error_class = 'CANCELLED', error_code = :reason, finished_at = now(),
               updated_at = now()
        WHERE connection_id = :id AND state IN ('QUEUED', 'RETRY')"""), {"id": connection_id, "reason": reason})
    return result.rowcount or 0


async def requeue(session, job: Job, progress: dict[str, Any], *, delay: timedelta = timedelta(0)) -> None:
    """Nhường slot: job giữ tiến độ (ví dụ page token) và tiếp tục sau.

    Lần thử được trả lại, vì hết ngân sách trang không phải là thất bại.
    """
    await fence(session, job)
    job.progress = progress
    await session.execute(text("""
        UPDATE jobs SET state = 'QUEUED', attempts = GREATEST(0, attempts - 1), lease_owner = NULL,
               lease_until = NULL, progress = CAST(:progress AS jsonb), run_after = now() + make_interval(secs => :delay),
               updated_at = now()
        WHERE id = :id"""), {"id": job.id, "progress": json.dumps(progress, default=str),
                             "delay": delay.total_seconds()})


async def state_of(session, job: Job) -> str | None:
    return (await session.execute(text("SELECT state FROM jobs WHERE id = :id"), {"id": job.id})).scalar_one_or_none()
