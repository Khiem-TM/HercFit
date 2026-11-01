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

Đường nền là trung vị trên một cửa sổ, kèm cỡ mẫu và
`algorithm_version`, để đổi phương pháp không bao giờ âm thầm đổi câu trả lời cũ.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from domains.health_records import ports
from domains.health_records.models.device_records import DailyHealthSummary
from domains.health_records.schemas.health import HEALTH_PROVIDER

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


def day_state(value: Any, column: str, availability: ports.TypeAvailability | None, day: date) -> str:
    if availability is None or not availability.enabled:
        return "UNSUPPORTED"
    if not availability.granted:
        return "NOT_GRANTED"
    if value is not None:
        return "ZERO" if column in COUNTED and float(value) == 0 else "OBSERVED"
    if availability.complete_through is None or day > availability.complete_through:
        return "NOT_SYNCED"
    return "NO_DATA"


async def daily_rows(session, user_id: UUID, start: date, end: date) -> dict[date, DailyHealthSummary]:
    rows = (await session.execute(select(DailyHealthSummary).where(
        DailyHealthSummary.user_id == user_id, DailyHealthSummary.source == HEALTH_PROVIDER,
        DailyHealthSummary.is_active.is_(True), DailyHealthSummary.local_date >= start,
        DailyHealthSummary.local_date <= end))).scalars()
    return {row.local_date: row for row in rows}


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


async def store_coverage(session, user_id: UUID, report: dict[str, dict[str, Any]]) -> int:
    written = 0
    for column, entry in report.items():
        for day, state in entry["by_day"].items():
            await session.execute(text("""
                INSERT INTO health_coverage (user_id, data_type, local_date, state, updated_at)
                VALUES (:user, :data_type, :day, :state, now())
                ON CONFLICT (user_id, data_type, local_date) DO UPDATE SET state = EXCLUDED.state, updated_at = now()
                WHERE health_coverage.state IS DISTINCT FROM EXCLUDED.state"""),
                {"user": user_id, "data_type": entry["data_type"], "day": date.fromisoformat(day), "state": state})
            written += 1
    return written


async def baselines(session, user_id: UUID, as_of: date, window_days: int = 28) -> dict[str, Baseline]:
    rows = await daily_rows(session, user_id, as_of - timedelta(days=window_days), as_of - timedelta(days=1))
    result = {}
    for metric in BASELINE_METRICS:
        values = [float(getattr(row, metric)) for row in rows.values() if getattr(row, metric) is not None]
        result[metric] = Baseline(
            metric=metric, value=round(statistics.median(values), 2) if values else None,
            spread=round(statistics.pstdev(values), 2) if len(values) > 1 else None, n=len(values),
            window_days=window_days, as_of=as_of)
    return result


async def stored_baselines(session, user_id: UUID, as_of: date, window_days: int) -> dict[str, Baseline]:
    rows = (await session.execute(text("""
        SELECT metric, value, spread, n FROM health_baselines
        WHERE user_id = :user AND as_of = :as_of AND window_days = :window AND algorithm_version = :version"""),
        {"user": user_id, "as_of": as_of, "window": window_days, "version": ALGORITHM_VERSION})).all()
    return {row.metric: Baseline(metric=row.metric, value=row.value, spread=row.spread, n=row.n,
                                 window_days=window_days, as_of=as_of) for row in rows if row.metric in BASELINE_METRICS}


async def baselines_for(session, user_id: UUID, end: date, window_days: int,
                        today: date | None = None) -> tuple[dict[str, Baseline], str]:
    """Đường nền cho một báo cáo kết thúc ở `end`, và cách có được chúng ("live" hay "stored").

    v1: cửa sổ kết thúc ở chính `end`, nên báo cáo cho hôm nay có một ngày chưa trọn.
    Bộ đọc v2 `analytics`: chỉ các ngày đã trọn (trước hôm nay), đọc từ những gì
    ANALYTICS_RECOMPUTE đã lưu cho ngày đó nếu có, ngược lại tính trực tiếp bằng
    cùng thuật toán, nên hai đường cho cùng con số.
    """
    from core.flags import reader_v2

    if not reader_v2("analytics"):
        return await baselines(session, user_id, end + timedelta(days=1), window_days), "live"
    from datetime import datetime, timezone

    today = today or datetime.now(timezone.utc).date()
    as_of = min(end + timedelta(days=1), today)
    stored = await stored_baselines(session, user_id, as_of, window_days)
    if len(stored) == len(BASELINE_METRICS):
        return stored, "stored"
    return await baselines(session, user_id, as_of, window_days), "live"


async def store_baselines(session, user_id: UUID, values: dict[str, Baseline]) -> None:
    for item in values.values():
        await session.execute(text("""
            INSERT INTO health_baselines (user_id, metric, window_days, as_of, algorithm_version, value, spread, n)
            VALUES (:user, :metric, :window, :as_of, :version, :value, :spread, :n)
            ON CONFLICT (user_id, metric, window_days, as_of, algorithm_version)
            DO UPDATE SET value = EXCLUDED.value, spread = EXCLUDED.spread, n = EXCLUDED.n, computed_at = now()"""),
            {"user": user_id, "metric": item.metric, "window": item.window_days, "as_of": item.as_of,
             "version": item.algorithm_version, "value": item.value, "spread": item.spread, "n": item.n})
