"""Độ phủ và đường nền: biết gì, thiếu gì, và vì sao.

Độ phủ theo (ngày, loại dữ liệu) là một trong
  OBSERVED      có giá trị (hoặc có mẫu dày trong vài giây)
  ZERO          giá trị đếm được đúng bằng 0 (ví dụ 0 tầng): là dữ liệu, không phải vắng mặt
  NO_DATA       loại này đã đồng bộ qua ngày đó và không có gì
  NOT_GRANTED   người dùng chưa cấp scope
  UNSUPPORTED   HercFit không đọc loại này (registry hoặc kiểm chứng)
  NOT_SYNCED    ngày đó mới hơn lần đọc trọn vẹn cuối cùng của loại này
Ít bước không bao giờ có nghĩa là "không đeo": việc đeo không suy ra từ mức hoạt động, chỉ từ
dữ liệu quan sát được, và được báo là chưa biết khi không có gì hỗ trợ.

Đường nền là trung vị trên các ngày đã trọn trước `as_of`, kèm cỡ mẫu và `algorithm_version`,
để đổi phương pháp không bao giờ âm thầm đổi câu trả lời cũ. Mọi thứ được tính lúc đọc từ
health_points (không có bảng cache).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from domains.analytics.services.daily_health.baseline import robust
from domains.health_records import ports, views

ALGORITHM_VERSION = "baseline-median-v1"
# Các cột theo ngày được theo dõi độ phủ, kèm loại dữ liệu nuôi chúng.
DAILY_SIGNALS = {
    "steps": "steps", "total_kcal": "total-calories", "active_minutes": "active-minutes",
    "resting_hr_bpm": "daily-resting-heart-rate", "hrv_ms": "daily-heart-rate-variability",
    "sleep_minutes": "sleep", "spo2_avg_pct": "daily-oxygen-saturation", "hydration_ml": "hydration-log",
}
COUNTED = {"steps", "active_minutes", "hydration_ml"}
BASELINE_METRICS = {"resting_hr_bpm": "Nhịp tim nghỉ", "hrv_ms": "HRV", "sleep_minutes": "Thời gian ngủ",
                    "steps": "Bước chân"}


@dataclass(frozen=True)
class Baseline:
    metric: str
    value: float | None
    spread: float | None
    n: int
    window_days: int
    as_of: date
    algorithm_version: str = ALGORITHM_VERSION
    # Độ lệch tuyệt đối trung vị (cùng đơn vị với chỉ số): độ phân tán bền với ngày ngoại lai.
    mad: float | None = None


def day_state(value: Any, column: str, availability: ports.TypeAvailability | None, day: date) -> str:
    if availability is None or not availability.enabled:
        return "UNSUPPORTED"
    if not availability.granted:
        return "NOT_GRANTED"
    if value is not None:
        return "ZERO" if column in COUNTED and float(value) == 0 else "OBSERVED"
    if (availability.complete_through is None or day > availability.complete_through
            or (availability.complete_from is not None and day < availability.complete_from)):
        return "NOT_SYNCED"
    return "NO_DATA"


async def daily_rows(session, user_id: UUID, start: date, end: date) -> dict[date, Any]:
    return {row.local_date: row for row in await views.daily(session, user_id, start, end)}


async def coverage(session, user_id: UUID, start: date, end: date) -> dict[str, dict[str, Any]]:
    """{column: {"by_day": {iso: state}, "observed_days": n, "days": total, "state": summary}}."""
    available = await ports.availability(session, user_id)
    rows = await daily_rows(session, user_id, start, end)
    days = [(start + timedelta(days=offset)) for offset in range((end - start).days + 1)]
    result = {}
    for column, data_type in DAILY_SIGNALS.items():
        states = {day.isoformat(): day_state(getattr(rows.get(day), column, None), column,
                                             available.get(data_type), day) for day in days}
        counts: dict[str, int] = {}
        for state in states.values():
            counts[state] = counts.get(state, 0) + 1
        observed = counts.get("OBSERVED", 0) + counts.get("ZERO", 0)
        summary = ("OBSERVED" if observed else max(counts, key=counts.get)) if counts else "NO_DATA"
        result[column] = {"data_type": data_type, "by_day": states, "observed_days": observed, "days": len(days),
                          "counts": counts, "state": summary}
    return result


async def baselines(session, user_id: UUID, as_of: date, window_days: int = 28) -> dict[str, Baseline]:
    rows = await daily_rows(session, user_id, as_of - timedelta(days=window_days), as_of - timedelta(days=1))
    result = {}
    for metric in BASELINE_METRICS:
        values = [float(getattr(row, metric)) for row in rows.values() if getattr(row, metric) is not None]
        found = robust(values)
        result[metric] = Baseline(
            metric=metric, value=round(found.median, 2) if found.median is not None else None,
            spread=round(statistics.pstdev(values), 2) if len(values) > 1 else None, n=found.n,
            window_days=window_days, as_of=as_of, mad=round(found.mad, 2) if found.mad is not None else None)
    return result


async def baselines_for(session, user_id: UUID, end: date, window_days: int,
                        today: date | None = None) -> dict[str, Baseline]:
    """Đường nền cho một báo cáo kết thúc ở `end`: chỉ các ngày đã trọn (trước hôm nay)."""
    from datetime import datetime, timezone

    today = today or datetime.now(timezone.utc).date()
    return await baselines(session, user_id, min(end + timedelta(days=1), today), window_days)
