"""Vòng lặp worker: lấy job, heartbeat, chạy, và biến lỗi thành lần thử lại theo lớp lỗi.

Mỗi slot lấy một job mỗi lần (SKIP LOCKED). Heartbeat gia hạn lease
khi handler chạy; nếu mất lease, lệnh ghi đã fence kế tiếp của handler
ném JobFenced và slot chuyển tiếp mà không đụng tới job. Handler kết thúc
job trong transaction cuối của chính nó; khi một handler trả về mà chưa kết thúc, runner
sẽ hoàn tất nó.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import tempfile
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

import httpx

from core.database import get_db_session
from core.jobs import queue, retry
from core.jobs.queue import Job, JobFenced
from integrations.google_health.client import GoogleHealthError, ReauthRequired
from integrations.google_health.ingest.jobs import ConnectionChanged, Context
from integrations.google_health import tokens

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 40
IDLE_SECONDS = 2.0
# Được chạm vào mỗi khi một slot truy cập được database (lấy job hoặc heartbeat): worker không phục vụ
# HTTP, nên healthcheck của container đọc tuổi của file này thay thế.
ALIVE_FILE = Path(tempfile.gettempdir()) / "hercfit-worker.alive"


def owner_name(slot: int) -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{slot}"


def _alive() -> None:
    with suppress(OSError):
        ALIVE_FILE.touch()


async def _heartbeat(job: Job, lost: asyncio.Event) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        async with get_db_session() as session:
            if not await queue.heartbeat(session, job):
                lost.set()
                return
        _alive()


async def _settle(job: Job, exc: BaseException) -> None:
    """Ghi lỗi vào job (đã fence: worker đã cũ không ghi gì)."""
    if isinstance(exc, JobFenced):
        return
    if isinstance(exc, ConnectionChanged):
        async with get_db_session() as session:
            await queue.cancel(session, job, "connection_changed")
        return
    if isinstance(exc, ReauthRequired):
        if job.connection_id:
            await tokens.mark_reauth(job.connection_id, job.connection_generation)
        async with get_db_session() as session:
            await queue.needs_attention(session, job, error_class="REAUTH", error_code="reauth_required")
        return
    if isinstance(exc, GoogleHealthError):
        error_class, code, retry_after = exc.error_class, exc.code, exc.retry_after
    elif isinstance(exc, TimeoutError):
        error_class, code, retry_after = "RATE_LIMIT", "local_quota", None
    else:
        error_class, code, retry_after = "BUG", type(exc).__name__, None
    decision, delay = retry.decide(error_class, job.attempts, job.max_attempts, retry_after)
    async with get_db_session() as session:
        if decision == "RETRY":
            await queue.retry(session, job, delay=delay, error_class=error_class, error_code=code)
        elif decision == "STOP":
            await queue.cancel(session, job, f"{error_class.lower()}:{code}"[:64])
        else:
            await queue.needs_attention(session, job, error_class=error_class, error_code=code)
    log = logger.warning if decision == "RETRY" else logger.error
    log("job_failed kind=%s class=%s code=%s decision=%s attempt=%s", job.kind, error_class, code, decision,
        job.attempts)


async def run_one(job: Job, handlers: dict, http: httpx.AsyncClient) -> None:
    handler = handlers.get(job.kind)
    if handler is None:
        async with get_db_session() as session:
            await queue.needs_attention(session, job, error_class="BUG", error_code="unknown_kind")
        return
    lost = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(job, lost))
    try:
        await handler(Context(job=job, http=http))
    except Exception as exc:  # noqa: BLE001 - mọi lỗi đều được phân loại và ghi lại
        with suppress(JobFenced):
            await _settle(job, exc)
    else:
        async with get_db_session() as session:
            if await queue.state_of(session, job) == "RUNNING":
                with suppress(JobFenced):
                    await queue.complete(session, job)
    finally:
        beat.cancel()
        with suppress(asyncio.CancelledError):
            await beat


async def drain(queues: tuple[str, ...], handlers: dict, http: httpx.AsyncClient, *, owner: str = "test",
                limit: int = 100) -> int:
    """Chạy các job sẵn sàng cho đến khi hết (test và CLI chạy một lần)."""
    done = 0
    while done < limit:
        async with get_db_session() as session:
            job = await queue.claim(session, queues, owner)
        if job is None:
            return done
        await run_one(job, handlers, http)
        done += 1
    return done


async def run(queues: tuple[str, ...], concurrency: int, handlers: dict, stop: asyncio.Event) -> None:
    async with httpx.AsyncClient() as http:
        async def slot(index: int) -> None:
            owner = owner_name(index)
            while not stop.is_set():
                try:
                    async with get_db_session() as session:
                        job = await queue.claim(session, queues, owner, lease=timedelta(seconds=120))
                    _alive()
                except Exception as exc:  # database tạm thời không truy cập được
                    logger.warning("job_claim_failed error=%s", type(exc).__name__)
                    job = None
                if job is None:
                    with suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(stop.wait(), IDLE_SECONDS)
                    continue
                await run_one(job, handlers, http)

        await asyncio.gather(*(slot(index) for index in range(concurrency)))
