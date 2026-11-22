"""Quên dữ liệu sức khoẻ mà trợ lý đang giữ khi người dùng thu hồi consent.

Backend phát `consent.changed` trong cùng transaction với quyết định
(domain_events). Consumer này, chạy bên trong service agent, xử lý mỗi
lần thu hồi một lần (domain_event_deliveries):

* transcript PostgreSQL thuộc người dùng, không bị xoá bởi thu hồi consent;
* checkpoint và toàn bộ summary/context bị xoá, generation cũ bị vô hiệu;
* lệnh đã duyệt chưa rõ kết quả chỉ giữ payload bất biến và khoá idempotency;
* episode sức khoẻ được tombstone để graph không dựng lại dữ kiện đã thu hồi.

Dữ kiện thiết bị trong graph đã được trigger của backend đánh tombstone. Bản
ghi chat hiển thị vẫn được giữ: đó là cuộc trò chuyện của người dùng, họ có thể tự xoá.
"""

from __future__ import annotations

import asyncio
import logging
import time

from agentic.tools.registry import REGISTRY

logger = logging.getLogger(__name__)
CONSUMER = "agentic.consent_purge"
POLL_SECONDS = 10
HEALTH_TOOLS = frozenset(name for name, spec in REGISTRY.items() if spec.domain == "health")
HEALTH_DOMAINS = frozenset({"health"})
HEALTH_RECORD_KINDS = frozenset({"DailyHealth", "SleepSession", "DeviceWorkout"})


def is_health_episode(data: dict) -> bool:
    """Một lượt đã ghi nhật ký (`tools`) hoặc lần thực thi (`tool`) có chạm tới dữ liệu sức khoẻ."""
    tools = [data["tool"]] if data.get("tool") else list(data.get("tools") or [])
    refs = data.get("resource_refs") or []
    return (
        data.get("domain") in HEALTH_DOMAINS
        or any(tool in HEALTH_TOOLS for tool in tools)
        or any(isinstance(ref, dict) and ref.get("kind") in HEALTH_RECORD_KINDS for ref in refs)
    )


async def purge_user_health(runtime, user_id: str) -> dict:
    sessions = threads_deleted = 0
    for session_id in await runtime.store.user_session_ids(user_id):
        sessions += 1
        async with runtime.store.session(session_id, user_id, create=False) as session:
            before = set(await runtime.store.threads(session_id))
            await runtime.prepare_session(session, user_id)
            threads_deleted += len(before - set(await runtime.store.threads(session_id)))
            if runtime.memory and session.get("memory_cache_cleanup_pending"):
                raise RuntimeError("Revoked cache cleanup is pending; retry delivery")
    episodes = await runtime.store.forget_episodes(user_id, is_health_episode)
    return {
        "sessions": sessions,
        "threads_deleted": threads_deleted,
        "checkpoints_rewritten": 0,
        "episodes_removed": sum(episodes.values()),
    }


async def purge_once(runtime, *, limit: int = 50) -> int:
    """Xử lý các sự kiện consent chưa giao; thu hồi thì dọn dữ liệu, cấp quyền thì chỉ xác nhận."""
    handled = 0
    async with runtime.store.pool.connection() as conn:
        async with conn.transaction():
            rows = await (
                await conn.execute(
                    """
                SELECT e.id, e.user_id, e.payload FROM domain_events e
                WHERE e.topic = 'consent.changed'
                  AND NOT EXISTS (SELECT 1 FROM domain_event_deliveries d WHERE d.consumer = %s AND d.event_id = e.id)
                ORDER BY e.id LIMIT %s FOR UPDATE OF e SKIP LOCKED""",
                    (CONSUMER, limit),
                )
            ).fetchall()
            for row in rows:
                payload = row["payload"] or {}
                if payload.get("purpose") == "assistant" and not payload.get("granted"):
                    result = await purge_user_health(runtime, str(row["user_id"]))
                    logger.info(
                        "consent_purge sessions=%s threads=%s rewritten=%s episodes=%s",
                        result["sessions"],
                        result["threads_deleted"],
                        result["checkpoints_rewritten"],
                        result["episodes_removed"],
                    )
                await conn.execute(
                    "INSERT INTO domain_event_deliveries (consumer, event_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (CONSUMER, row["id"]),
                )
                handled += 1
    return handled


async def purge_forever(runtime) -> None:
    from agentic.observability import metrics

    while True:
        try:
            await purge_once(runtime)
            metrics.gauge("worker_last_success_ts", time.time(), worker="consent_purge")
        except Exception as exc:  # noqa: BLE001 - vòng lặp nền phải sống sót qua lỗi tạm thời
            # Trước đây lỗi bị nuốt im lặng: lệnh xoá theo consent có thể kẹt mà không ai thấy.
            logger.warning("consent_purge_failed error_type=%s", type(exc).__name__)
            metrics.incr("worker_failures_total", worker="consent_purge", error=type(exc).__name__)
        await asyncio.sleep(POLL_SECONDS)
