"""Coverage and baselines: what is known, what is missing, and why.

Coverage per (day, data type) is one of
  OBSERVED      a value exists (or dense samples for some seconds)
  ZERO          a counted value of exactly 0 (e.g. 0 floors): data, not absence
  NO_DATA       the type was synced through that day and nothing exists
  NOT_GRANTED   the user did not grant the scope
  UNSUPPORTED   HercFit does not read this type (registry or verification)
  NOT_SYNCED    the day is newer than the type's last complete read
Few steps never means "not worn": wear is not inferred from activity, only from
observed data, and is reported as unknown when nothing supports it.

Baselines are medians over a window with their sample size and an
`algorithm_version`, so a changed method never silently changes old answers.
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
# Daily columns tracked for coverage, with the data type that feeds them.
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
    """Baselines for a report ending on `end`, and how they were obtained ("live" or "stored").

    v1: the window ends with `end` itself, so a report for today includes a partial day.
    Reader v2 `analytics`: complete days only (before today), read from what
    ANALYTICS_RECOMPUTE stored for that day when present, otherwise computed live with
    the same algorithm, so both paths give the same numbers.
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
