"""Đọc Google Health về `health_points`: Google là nguồn sự thật cho dữ liệu đo bằng thiết bị.

Với mỗi loại đã được cấp quyền đọc (domains/health_records/types.py), cho cửa sổ ngày địa phương
[start, end):
1. Đọc bằng reconcile (luồng gộp mọi nguồn, đã khử trùng lặp), dailyRollUp (tổng theo ngày) hoặc
   list (ECG, IRN không có reconcile). Dạng bản ghi do interface trong kinds.py xử lý.
2. Loại HercFit ghi xuyên qua (buổi thể thao, cân nặng, nước...): thêm một lần reconcile
   self-sources để biết điểm nào do HercFit ghi (ReconciledDataPoint không mang dataSource).
3. Bỏ các buổi gym HercFit đã tạo trên Google (google_pushes): chúng đã nằm trong bảng trainings.
4. Chỉ khi đọc trọn vẹn mọi trang mới thay thế cửa sổ: upsert theo tên Google và xoá điểm Google
   không còn giữ. Đọc dở hay lỗi thì giữ nguyên dữ liệu cũ của loại đó và ghi lý do vào
   `sync_cursor`; một loại lỗi không bao giờ chặn loại khác.
5. Phát lại dữ kiện graph của cửa sổ (views.publish_kg), kèm tombstone cho những gì đã biến mất.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Iterator
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from core.database import get_db_session
from domains.health_records import views
from domains.health_records.models.health_points import HealthPoint as HealthPointRow
from domains.health_records.types import SELF_MARKED, DataType, Read, readable
from integrations.google_health import kinds
from integrations.google_health.client import (
    PERMISSION,
    GoogleHealthClient,
    GoogleHealthError,
    ReauthRequired,
)

logger = logging.getLogger(__name__)
LIST_WINDOW_DAYS = 90
HOUR_SECONDS = 3600


def chunks(start: date, end: date, days: int) -> Iterator[tuple[date, date]]:
    while start < end:
        stop = min(end, start + timedelta(days=days))
        yield start, stop
        start = stop


async def fetch(client: GoogleHealthClient, t: DataType, start: date, end: date, zone: str, *,
                family: str | None = None) -> tuple[list[kinds.HealthPoint], bool]:
    """(các điểm có ngày địa phương trong [start, end), đã đọc trọn mọi trang hay chưa)."""
    points: list[kinds.HealthPoint] = []
    complete = True
    rollup = t.read in (Read.DAILY_ROLLUP, Read.HOURLY_ROLLUP)
    for low, high in chunks(start, end, t.chunk_days if rollup else LIST_WINDOW_DAYS):
        if t.read is Read.HOURLY_ROLLUP:
            # Nửa đêm địa phương → nửa đêm địa phương: mỗi cửa sổ giờ nằm trọn trong một ngày.
            local = ZoneInfo(zone)
            result = await client.rollup_all(t.google_id, datetime.combine(low, time.min, local),
                                             datetime.combine(high, time.min, local),
                                             window_seconds=HOUR_SECONDS, page_size=t.page_size)
        elif rollup:
            result = await client.daily_rollup_all(t.google_id, low, high, page_size=t.page_size)
        else:
            result = await client.list_all(t.google_id, filter=kinds.filter_for(t, low, high), page_size=t.page_size,
                                           reconcile=t.read is Read.RECONCILE, family=family)
        complete = complete and result.complete
        for raw in result.points:
            point = kinds.parse(t, raw, zone)
            # ECG chỉ lọc được cận dưới: bỏ điểm sau cửa sổ.
            if point is not None and start <= point.local_date < end:
                points.append(point)
    return points, complete


async def pushed_names(user_id: UUID) -> set[str]:
    """Tên các điểm HercFit đã tạo cho buổi gym / bữa ăn (không gồm phiên đồng hồ được gắn vào gym)."""
    async with get_db_session() as session:
        rows = await session.execute(text("SELECT unnest(names) FROM google_pushes WHERE user_id = :u AND owned"),
                                     {"u": user_id})
        return {name for (name,) in rows}


async def pull(client: GoogleHealthClient, user_id: UUID, granted: list[str], start: date, end: date,
               zone: str, skip: frozenset[str] = frozenset()) -> dict[str, dict[str, Any]]:
    """Đồng bộ [start, end) cho mọi loại đọc được, trừ các loại người dùng đã tắt (`skip`);
    trả về trạng thái từng loại cho `sync_cursor`."""
    async with get_db_session() as session:
        before = await views.kg_facts(session, user_id, start, end - timedelta(days=1))
    pushed = await pushed_names(user_id)
    status: dict[str, dict[str, Any]] = {}
    for t in readable(granted, skip):
        try:
            points, complete = await fetch(client, t, start, end, zone)
            own: set[str] = set()
            if complete and t.id in SELF_MARKED:
                mine, complete = await fetch(client, t, start, end, zone, family="self-sources")
                own = {point.remote_name for point in mine}
        except ReauthRequired:
            raise
        except GoogleHealthError as exc:
            status[t.id] = {"error": "not_granted" if exc.error_class == PERMISSION else exc.code}
            logger.warning("google_health_pull_failed type=%s code=%s", t.id, exc.code)
            continue
        if not complete:
            status[t.id] = {"error": "incomplete"}
            continue
        rows = [point.row(user_id, written_by_hercfit=point.remote_name in own)
                for point in points if point.remote_name not in pushed]
        async with get_db_session() as session:
            written, removed = await HealthPointRow.replace_window(session, user_id, t.id, start, end, rows)
        status[t.id] = {"through": (end - timedelta(days=1)).isoformat(), "error": None, "rows": written,
                        "removed": removed}
    async with get_db_session() as session:
        await views.publish_kg(session, user_id, start, end - timedelta(days=1), before=before.keys())
    return status
