"""Một lượt đồng bộ Google Health cho một người dùng: đọc (pull) rồi đẩy (push).

1. Advisory lock theo kết nối: hai lượt không bao giờ chạy chồng; lượt đến sau trả "running".
2. Lấy access token (tokens.py: làm mới một lần dưới khoá). invalid_grant → NEEDS_REAUTH.
3. Làm mới hồ sơ và cài đặt Google (tuổi, múi giờ) để ngày địa phương và hồ sơ sức khoẻ đúng.
4. pull: thay thế cửa sổ của mọi loại đọc được. Lần đầu (chưa có trạng thái) đọc BACKFILL_DAYS ngày,
   sau đó RECENT_DAYS ngày gần nhất (đồng hồ có thể đồng bộ muộn).
5. push: đẩy gym và bữa ăn. Chạy sau pull vì cần phiên đồng hồ mới nhất để gắn buổi gym.
6. Ghi trạng thái từng loại vào `sync_cursor` và last_sync_at / last_success_at / last_error_code.

Không giữ transaction nào trong lúc gọi Google; mỗi lần ghi DB là một transaction ngắn.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text

from core.database import get_async_engine, get_db_session
from domains.health_records.types import disabled_types
from domains.shared import events
from domains.shared.schemas.tracking import DEFAULT_TIMEZONE
from integrations.google_health import fencing, tokens
from integrations.google_health.client import GoogleHealthClient, GoogleHealthError, ReauthRequired
from integrations.google_health.models import HealthConnection
from integrations.google_health.pull import pull
from integrations.google_health.push import push_pending

logger = logging.getLogger(__name__)
BACKFILL_DAYS = 90
RECENT_DAYS = 7
# Tần suất "hourly": vòng nền đồng bộ lại khi lượt gần nhất đã cũ hơn chừng này (chừa lệch nhịp của vòng lặp).
HOURLY = timedelta(minutes=55)


def provider_profile(profile: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    age = profile.get("age")
    values = {
        "age": age if isinstance(age, int) and not isinstance(age, bool) and 0 < age < 130 else None,
        "walking_stride_mm": profile.get("userConfiguredWalkingStrideLengthMm") or profile.get("autoWalkingStrideLengthMm"),
        "running_stride_mm": profile.get("userConfiguredRunningStrideLengthMm") or profile.get("autoRunningStrideLengthMm"),
        "weight_unit": settings.get("weightUnit"), "height_unit": settings.get("heightUnit"),
        "distance_unit": settings.get("distanceUnit"), "water_unit": settings.get("waterUnit"),
    }
    return {key: value for key, value in values.items() if value is not None}


def provider_timezone(settings: dict[str, Any]) -> str | None:
    zone = settings.get("timeZone")
    try:
        return zone if isinstance(zone, str) and ZoneInfo(zone) else None
    except (ValueError, KeyError):  # ZoneInfoNotFoundError là một KeyError
        return None


def merge_cursor(cursor: dict[str, Any], status: dict[str, dict[str, Any]], start: date) -> dict[str, Any]:
    """Giữ ngày sớm nhất đã đọc trọn (`from`) và ngày muộn nhất (`through`) của từng loại."""
    merged = dict(cursor)
    for data_type, entry in status.items():
        previous = merged.get(data_type) or {}
        if entry.get("error"):
            merged[data_type] = {**previous, "error": entry["error"]}
            continue
        earliest = min(filter(None, (previous.get("from"), start.isoformat())))
        merged[data_type] = {"from": earliest, "through": entry["through"], "error": None}
    return merged


async def run(user_id: UUID, *, days: int | None = None, push_only: bool = False,
              http: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Đồng bộ một người dùng; an toàn khi gọi chồng (lượt sau trả về "running").

    `push_only`: chỉ đẩy gym / bữa ăn / bản ghi sức khoẻ vừa đổi (hook ghi), không đọc lại Google."""
    async with get_db_session() as session:
        connection = await HealthConnection.for_user(session, user_id)
    if connection is None or connection.status != "ACTIVE":
        return {"status": "not_connected"}
    # Khoá theo phiên trên một kết nối autocommit: không có transaction nào mở trong lúc gọi Google.
    async with get_async_engine().connect() as lock:
        lock = await lock.execution_options(isolation_level="AUTOCOMMIT")
        key = {"key": f"gh-sync:{connection.id}"}
        if not (await lock.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), key)).scalar():
            return {"status": "running"}
        marker = fencing.current.set(fencing.SyncFence(connection.id, connection.sync_generation))
        try:
            await fencing.before_request()
            if http is not None:
                return await _run(connection, days, push_only, http)
            async with httpx.AsyncClient() as client:
                return await _run(connection, days, push_only, client)
        except fencing.SyncSuperseded:
            return {"status": "superseded"}
        finally:
            fencing.current.reset(marker)
            await lock.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), key)


async def _run(connection: HealthConnection, days: int | None, push_only: bool,
               http: httpx.AsyncClient) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        token, granted = await tokens.access_token(connection.id, http)
        client = GoogleHealthClient(token, http)
        zone = connection.timezone or DEFAULT_TIMEZONE
        today = datetime.now(ZoneInfo(zone)).date()
        end = today + timedelta(days=1)
        if push_only:
            pushed = await push_pending(client, connection.user_id, today - timedelta(days=BACKFILL_DAYS - 1), end, zone,
                                        granted)
            return {"status": "ok", "push": pushed}
        profile, settings = await _profile(client)
        zone = provider_timezone(settings) or zone
        span = days or (RECENT_DAYS if connection.sync_cursor else BACKFILL_DAYS)
        start = today - timedelta(days=span - 1)
        status = await pull(client, connection.user_id, granted, start, end, zone,
                            skip=disabled_types(connection.sync_groups))
        pushed = await push_pending(client, connection.user_id, today - timedelta(days=BACKFILL_DAYS - 1), end, zone,
                                    granted)
    except ReauthRequired:
        await tokens.mark_reauth(connection.id, generation=connection.sync_generation)
        return {"status": "needs_reauth"}
    except GoogleHealthError as exc:
        await _finish(connection.id, started, error=exc.code)
        logger.warning("google_health_sync_failed user=%s code=%s", connection.user_id, exc.code)
        return {"status": "error", "error": exc.code}
    failed = sorted(data_type for data_type, entry in status.items() if entry.get("error"))
    await _finish(connection.id, started, status=status, start=start, zone=zone,
                  profile=provider_profile(profile, settings), error=f"partial:{len(failed)}" if failed else None)
    return {"status": "partial" if failed else "ok", "window": [start.isoformat(), today.isoformat()],
            "types": status, "push": pushed}


async def _profile(client: GoogleHealthClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hồ sơ và cài đặt của Google; thiếu scope profile/settings thì bỏ qua."""
    try:
        return await client.get_profile(), await client.get_settings()
    except GoogleHealthError:
        return {}, {}


async def _finish(connection_id: UUID, started: datetime, *, status: dict[str, dict[str, Any]] | None = None,
                  start: date | None = None, zone: str | None = None, profile: dict[str, Any] | None = None,
                  error: str | None = None) -> None:
    async with get_db_session() as session:
        await fencing.check(session)
        connection = (await session.execute(select(HealthConnection).where(HealthConnection.id == connection_id)
                                            .with_for_update())).scalar_one()
        connection.last_sync_at = started
        connection.last_error_code = error
        if status is not None:
            connection.sync_cursor = merge_cursor(connection.sync_cursor or {}, status, start)
            connection.last_success_at = started
            # Cùng transaction với last_success_at: briefing/insight phản ứng theo dữ liệu mới (chỉ id và ngày).
            await events.publish(session, "health.synced", connection.user_id,
                                 {"connection_id": str(connection.id), "through": datetime.now(ZoneInfo(
                                     zone or connection.timezone or DEFAULT_TIMEZONE)).date().isoformat()})
        if zone:
            connection.timezone = zone
        if profile:
            connection.provider_profile = profile


def due(connection: HealthConnection, now: datetime) -> bool:
    """Vòng nền chỉ đồng bộ kết nối "hourly" đã tới lượt; "open" và "manual" do người dùng kích hoạt."""
    if (connection.sync_frequency or "hourly") != "hourly":
        return False
    return connection.last_sync_at is None or now - connection.last_sync_at >= HOURLY


async def sync_all(days: int | None = None, *, scheduled: bool = False) -> int:
    """Một lượt cho mọi kết nối đang hoạt động (CLI), hoặc chỉ những kết nối tới lượt (`scheduled`, vòng nền)."""
    now = datetime.now(timezone.utc)
    async with get_db_session() as session:
        connections = list((await session.execute(select(HealthConnection).where(
            HealthConnection.status == "ACTIVE", HealthConnection.is_active.is_(True)))).scalars())
    users = [connection.user_id for connection in connections if not scheduled or due(connection, now)]
    for user_id in users:
        try:
            await run(user_id, days=days)
        except Exception as exc:  # một người dùng lỗi không bao giờ chặn người khác
            logger.warning("google_health_sync_error user=%s error=%s", user_id, type(exc).__name__)
    return len(users)
