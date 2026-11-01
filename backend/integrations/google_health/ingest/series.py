"""Chuỗi dày (nhịp tim, khoảng bước chân, HRV, SpO2, ...) dưới dạng chunk nén.

Mã hoá `zjson1`: zlib(JSON{"v": 1, "fields": [...], "rows": [[dt, dur, f1, f2, ...]]}) trong đó
`dt` là số giây tính từ đầu chunk và `dur` là độ dài khoảng (0 với mẫu).
Các cột lấy từ schema giá trị (đã bỏ trường thời gian), nên không đoán gì
và không bỏ gì; `metric` gọi tên cột nuôi min/max/sum.

Mỗi (người dùng, loại, nguồn, chu kỳ) là một chunk: các nguồn không bao giờ bị gộp, nên một
đồng hồ và một điện thoại cùng đo một phút vẫn là hai quan sát. Một lần đọc trọn
một ngày UTC sẽ thay các chunk của ngày đó; lần đọc dở thì không bao giờ.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from integrations.google_health.adapters.base import Parsed
from integrations.google_health.contract.registry import DISCOVERY_REVISION

ENCODING = "zjson1"
HOURLY = frozenset({"heart-rate"})
# Cột có thống kê được giữ theo từng chunk (None: chỉ đếm).
METRIC = {
    "heart-rate": "beatsPerMinute", "heart-rate-variability": "rootMeanSquareOfSuccessiveDifferencesMilliseconds",
    "oxygen-saturation": "percentage", "steps": "count", "distance": "millimeters", "floors": "count",
    "altitude": "gainMillimeters", "active-energy-burned": "kcal", "basal-energy-burned": "kcal",
    "active-zone-minutes": "activeZoneMinutes", "swim-lengths-data": "strokeCount",
    "skin-temperature-sensors": "temperatureCelsius",
}
TIME_FIELDS = {"interval", "sampleTime"}


@dataclass
class Chunk:
    data_type: str
    source_key: str
    start: datetime
    end: datetime
    resolution: str
    fields: list[str]
    rows: list[list[Any]]
    metric: str | None

    def encode(self) -> bytes:
        return zlib.compress(json.dumps({"v": 1, "fields": self.fields, "rows": self.rows}, separators=(",", ":"),
                                        default=str).encode(), 6)

    def stats(self) -> dict[str, Any]:
        values = []
        if self.metric and self.metric in self.fields:
            index = 2 + self.fields.index(self.metric)
            values = [row[index] for row in self.rows if isinstance(row[index], (int, float))]
        covered = sum(row[1] for row in self.rows if isinstance(row[1], (int, float)))
        return {"value_min": min(values) if values else None, "value_max": max(values) if values else None,
                "value_sum": float(sum(values)) if values else None, "covered_seconds": int(covered)}


from domains.health_records.series import decode  # noqa: E402,F401  (bộ đọc sở hữu việc giải mã)


def utc_day(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, timezone.utc)
    return start, start + timedelta(days=1)


def _period(data_type: str, moment: datetime) -> tuple[datetime, datetime, str]:
    moment = moment.astimezone(timezone.utc)
    if data_type in HOURLY:
        start = moment.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=1), "hour"
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1), "day"


def _flatten(value: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    readings = value.get("sensorData")
    if isinstance(readings, list):
        # Nhiệt độ da v4beta: mỗi mẫu có nhiều số đo cảm biến; cột là trung bình của chúng.
        temps = [r.get("temperatureCelsius") for r in readings if isinstance(r, dict)
                 and isinstance(r.get("temperatureCelsius"), (int, float))]
        flat["temperatureCelsius"] = round(sum(temps) / len(temps), 3) if temps else None
        flat["readings"] = len(readings)
    for key, item in value.items():
        if key in TIME_FIELDS or (key == "sensorData" and "readings" in flat):
            continue
        if isinstance(item, dict):
            for inner, inner_value in item.items():
                flat[f"{key}.{inner}"] = inner_value
        else:
            flat[key] = item
    return flat


def build(data_type: str, points: list[tuple[Parsed, str]]) -> list[Chunk]:
    """Gom các điểm đã phân tích (kèm khoá nguồn) thành chunk theo nguồn và chu kỳ."""
    groups: dict[tuple[str, datetime], dict[str, Any]] = {}
    for parsed, source_key in points:
        start = parsed.time.physical_start
        if start is None:
            continue
        period_start, period_end, resolution = _period(data_type, start)
        group = groups.setdefault((source_key, period_start), {"end": period_end, "resolution": resolution,
                                                               "points": []})
        end = parsed.time.physical_end or start
        group["points"].append((start, max(0.0, (end - start).total_seconds()), _flatten(parsed.value)))
    chunks = []
    for (source_key, period_start), group in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        fields = sorted({name for _, _, values in group["points"] for name in values})
        rows = [[round((start - period_start).total_seconds(), 3), round(duration, 3),
                 *[values.get(name) for name in fields]]
                for start, duration, values in sorted(group["points"], key=lambda point: point[0])]
        chunks.append(Chunk(data_type, source_key, period_start, group["end"], group["resolution"], fields, rows,
                            METRIC.get(data_type)))
    return chunks


def rows_for_insert(chunks: list[Chunk], *, user_id, connection_id, retention_until: date | None) -> list[dict]:
    from domains.shared.models.basemodel import uuid7

    rows = []
    for chunk in chunks:
        blob = chunk.encode()
        rows.append({"id": uuid7(), "user_id": user_id, "connection_id": connection_id, "data_type": chunk.data_type,
                     "source_key": chunk.source_key, "chunk_start": chunk.start, "chunk_end": chunk.end,
                     "resolution": chunk.resolution, "sample_count": len(chunk.rows), "encoding": ENCODING,
                     "data": blob, "sha256": hashlib.sha256(blob).hexdigest(), "schema_revision": DISCOVERY_REVISION,
                     "retention_until": retention_until, **chunk.stats()})
    return rows
