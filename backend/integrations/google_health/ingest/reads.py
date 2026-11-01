"""How each Google Health data type is read for a civil-date window.

Filters follow the list method's documented grammar (discovery revision in
contract/registry.py): only `>=` and `<` with AND, on

* `{type}.date` for daily points,
* `{type}.sample_time.civil_time` for samples,
* `{type}.interval.civil_start_time` for intervals and sessions,
* `sleep.interval.civil_end_time` (sleep belongs to the date the user woke up),
* `electrocardiogram.interval.start_time >=` only (no upper bound is supported;
  the caller drops points after the window).

Civil filters select by the wall-clock date recorded with each point, so the
user's current timezone never decides which history a window contains.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterator

from integrations.google_health.contract import discovery
from integrations.google_health.contract.registry import DataTypeSpec, Op, spec

# Earliest UTC offset in use (UTC+14): a physical lower bound that cannot miss a civil date.
MAX_AHEAD = timedelta(hours=14)
MAX_PAGES = 50


@dataclass(frozen=True)
class ReadPlan:
    data_type: str
    method: str                 # "dailyRollUp" or "list"
    page_size: int
    chunk_days: int | None      # dailyRollUp ranges are capped per type
    filter_fn: str              # which filter builder applies (for logging and tests)


def _shape(item: DataTypeSpec, api_version: str) -> str:
    info = discovery.data_point_types(api_version).get(item.id)
    if info is None:
        return "none"
    properties = discovery.schemas(api_version)[info["schema"]].get("properties", {})
    if "date" in properties:
        return "date"
    if "sampleTime" in properties:
        return "sample"
    if "interval" in properties:
        return "interval"
    return "none"


def plan(data_type: str, *, rollup: bool, api_version: str = "v4") -> ReadPlan:
    item = spec(data_type)
    if rollup:
        if Op.DAILY_ROLLUP not in item.read_ops:
            raise ValueError(f"{data_type} has no dailyRollUp")
        return ReadPlan(data_type, "dailyRollUp", item.daily_rollup_page_size, item.max_range_days, "range")
    if Op.LIST not in item.read_ops:
        raise ValueError(f"{data_type} has no list")
    if data_type == "sleep":
        kind = "sleep_civil_end"
    elif data_type == "electrocardiogram":
        kind = "ecg_start"
    else:
        kind = _shape(item, api_version)
    return ReadPlan(data_type, "list", item.list_page_size, None, kind)


def list_filter(read: ReadPlan, start: date, end_exclusive: date) -> str | None:
    path = spec(read.data_type).filter_path
    low, high = start.isoformat(), end_exclusive.isoformat()
    if read.filter_fn == "date":
        return f'{path}.date >= "{low}" AND {path}.date < "{high}"'
    if read.filter_fn == "sample":
        return f'{path}.sample_time.civil_time >= "{low}" AND {path}.sample_time.civil_time < "{high}"'
    if read.filter_fn == "interval":
        return f'{path}.interval.civil_start_time >= "{low}" AND {path}.interval.civil_start_time < "{high}"'
    if read.filter_fn == "sleep_civil_end":
        return f'sleep.interval.civil_end_time >= "{low}" AND sleep.interval.civil_end_time < "{high}"'
    if read.filter_fn == "ecg_start":
        lower = datetime.combine(start, time.min, timezone.utc) - MAX_AHEAD
        return f'electrocardiogram.interval.start_time >= "{lower.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
    return None


def chunks(start: date, end_exclusive: date, days: int) -> Iterator[tuple[date, date]]:
    while start < end_exclusive:
        stop = min(end_exclusive, start + timedelta(days=days))
        yield start, stop
        start = stop
