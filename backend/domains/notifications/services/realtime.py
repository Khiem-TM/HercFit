"""Đẩy thông báo tức thì qua WebSocket: /api/v2/notifications/stream.

Phát: `publish` gọi pg_notify trong transaction của bên ghi, nên PostgreSQL chỉ giao sự kiện khi thay đổi đã
commit (rollback thì không có gì). Payload chỉ có định danh {user, id, event}, không có nội dung sức khoẻ.

Nhận: mỗi tiến trình backend có một kết nối psycopg autocommit LISTEN kênh này (`listen_loop`). Tiến trình nào
đang giữ socket của người dùng đó thì đọc dòng thông báo và đẩy xuống (`Hub`). Mất kết nối DB thì nối lại có
giãn cách và báo `resync` để client tải lại hộp thư (có thể đã lỡ sự kiện trong lúc mất kết nối).

Xác thực: tin nhắn đầu tiên {"type": "auth", "token": "<access token>"} trong AUTH_TIMEOUT giây; token không
nằm trong URL (URL bị ghi log). Chỉ access token của người dùng (token uỷ quyền của trợ lý khác audience nên
bị từ chối). Socket đóng 4401 khi token hết hạn để client làm mới token rồi nối lại.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from core.database import get_db_session, get_postgres_connection_string

logger = logging.getLogger(__name__)
CHANNEL = "hercfit_notifications"
EVENTS = ("created", "seen", "dismissed")
AUTH_TIMEOUT = 10.0
PING_SECONDS = 30.0
MAX_SOCKETS = 5
QUEUE_SIZE = 64
UNAUTHORIZED, TOO_MANY = 4401, 4429


async def publish(session, user_id: UUID, event: str, notification_id: UUID) -> None:
    """Giao khi transaction của `session` commit (NOTIFY trong transaction)."""
    if event not in EVENTS:
        raise ValueError(f"Unknown notification event {event!r}")
    payload = json.dumps({"user": str(user_id), "id": str(notification_id), "event": event})
    await session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": payload})


class Hub:
    """Các socket đang mở của tiến trình này, theo người dùng."""

    def __init__(self) -> None:
        self._queues: dict[UUID, set[asyncio.Queue]] = {}

    def count(self, user_id: UUID) -> int:
        return len(self._queues.get(user_id, ()))

    @contextmanager
    def subscribe(self, user_id: UUID) -> Iterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(QUEUE_SIZE)
        self._queues.setdefault(user_id, set()).add(queue)
        try:
            yield queue
        finally:
            queues = self._queues.get(user_id, set())
            queues.discard(queue)
            if not queues:
                self._queues.pop(user_id, None)

    def push(self, user_id: UUID, message: dict[str, Any]) -> None:
        for queue in list(self._queues.get(user_id, ())):
            _offer(queue, message)

    def broadcast(self, message: dict[str, Any]) -> None:
        for queues in list(self._queues.values()):
            for queue in list(queues):
                _offer(queue, message)


def _offer(queue: asyncio.Queue, message: dict[str, Any]) -> None:
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:  # client quá chậm: bỏ hàng đợi, bảo nó tải lại toàn bộ
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait({"type": "resync"})


hub = Hub()


async def message_for(session, user_id: UUID, event: str, notification_id: UUID) -> dict[str, Any] | None:
    from domains.notifications.models.notification import UserNotification
    from domains.notifications.schemas.notification import NotificationRead

    found = await UserNotification.owned(session, user_id, notification_id)
    if found is None:
        return None
    unread = await UserNotification.unread_count(session, user_id, now=datetime.now(timezone.utc))
    if event == "created":
        return {"type": "notification.created", "unread": unread,
                "notification": NotificationRead.model_validate(found).model_dump(mode="json")}
    if event == "seen":
        return {"type": "notification.seen", "id": str(notification_id), "unread": unread,
                "seen_at": found.seen_at.isoformat() if found.seen_at else None}
    return {"type": "notification.dismissed", "id": str(notification_id), "unread": unread}


async def dispatch(target: Hub, payload: str) -> None:
    try:
        data = json.loads(payload)
        user_id, notification_id, event = UUID(data["user"]), UUID(data["id"]), data["event"]
    except (ValueError, KeyError, TypeError):
        return
    if event not in EVENTS or not target.count(user_id):
        return
    async with get_db_session() as session:
        message = await message_for(session, user_id, event, notification_id)
    if message is not None:
        target.push(user_id, message)


async def listen_loop(target: Hub = hub) -> None:
    import psycopg

    delay, connected_before = 1.0, False
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(get_postgres_connection_string(),
                                                             autocommit=True) as connection:
                await connection.execute(f"LISTEN {CHANNEL}")
                if connected_before:
                    target.broadcast({"type": "resync"})
                connected_before, delay = True, 1.0
                async for notify in connection.notifies():
                    try:
                        await dispatch(target, notify.payload)
                    except Exception as exc:  # một sự kiện lỗi không dừng vòng nghe
                        logger.warning("notification_dispatch_error error=%s", type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("notification_listen_error error=%s retry_in=%s", type(exc).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


# ---------------------------------------------------------------------------- socket

async def _close(websocket, code: int) -> None:
    with suppress(Exception):
        await websocket.close(code=code)


async def authenticate(websocket) -> tuple[UUID, float] | None:
    """(user_id, exp) từ tin nhắn đầu tiên, hoặc None khi không hợp lệ hay quá hạn chờ."""
    from core.security import decode_access_token

    try:
        message = json.loads(await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT))
        if not isinstance(message, dict) or message.get("type") != "auth":
            return None
        claims = decode_access_token(str(message.get("token") or ""))
        return UUID(str(claims["sub"])), float(claims["exp"])
    except (asyncio.TimeoutError, ValueError, KeyError, TypeError, HTTPException):
        return None
    except Exception:  # client ngắt kết nối trước khi xác thực
        return None


async def _sender(websocket, queue: asyncio.Queue) -> None:
    while True:
        try:
            message = await asyncio.wait_for(queue.get(), PING_SECONDS)
        except asyncio.TimeoutError:
            message = {"type": "ping"}
        await websocket.send_json(message)


async def _receiver(websocket) -> None:
    while True:  # client chỉ gửi "pong"; vòng này chủ yếu để phát hiện ngắt kết nối
        await websocket.receive_text()


async def stream(websocket, target: Hub = hub) -> None:
    from domains.identity.models.user import User
    from domains.notifications.models.notification import UserNotification

    await websocket.accept()
    identity = await authenticate(websocket)
    if identity is None:
        await _close(websocket, UNAUTHORIZED)
        return
    user_id, expires = identity
    async with get_db_session() as session:
        user = await User.get_by_id(session, user_id)
        unread = await UserNotification.unread_count(session, user_id, now=datetime.now(timezone.utc)) \
            if user is not None and user.is_active else None
    if unread is None:
        await _close(websocket, UNAUTHORIZED)
        return
    if target.count(user_id) >= MAX_SOCKETS:
        await _close(websocket, TOO_MANY)
        return
    with target.subscribe(user_id) as queue:
        await websocket.send_json({"type": "ready", "unread": unread})
        tasks = {asyncio.create_task(_sender(websocket, queue)), asyncio.create_task(_receiver(websocket))}
        done, pending = await asyncio.wait(tasks, timeout=max(1.0, expires - time.time()),
                                           return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if not task.cancelled():
                task.exception()  # lấy lỗi ra để asyncio không cảnh báo: lỗi ở đây là client đã ngắt kết nối
        if not done:
            await _close(websocket, UNAUTHORIZED)  # token hết hạn: client làm mới rồi nối lại
