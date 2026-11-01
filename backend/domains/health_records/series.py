"""Reading dense series chunks (encoding `zjson1`, written by the provider integration).

`window(...)` returns points per source between two instants, optionally reduced
to minute or hour buckets (mean of the metric column, count of samples). Sources
are kept apart: two devices measuring the same minute are two series.
"""
from __future__ import annotations

import json
import zlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import undefer

from domains.health_records.models.sources import HealthSeriesChunk


def decode(blob: bytes) -> dict[str, Any]:
    return json.loads(zlib.decompress(blob))


def _bucket(moment: datetime, resolution: str) -> datetime:
    if resolution == "minute":
        return moment.replace(second=0, microsecond=0)
    if resolution == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    return moment


async def window(session, user_id, data_type: str, start: datetime, end: datetime, *, resolution: str = "minute",
                 metric: str | None = None, max_points: int = 20_000) -> dict[str, Any]:
    chunks = (await session.execute(select(HealthSeriesChunk).options(undefer(HealthSeriesChunk.data)).where(
        HealthSeriesChunk.user_id == user_id, HealthSeriesChunk.data_type == data_type,
        HealthSeriesChunk.chunk_end > start, HealthSeriesChunk.chunk_start < end,
    ).order_by(HealthSeriesChunk.source_key, HealthSeriesChunk.chunk_start))).scalars().all()
    sources: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        body = decode(chunk.data)
        fields = body["fields"]
        column = (metric if metric in fields else fields[0]) if fields else None
        index = 2 + fields.index(column) if column else None
        entry = sources.setdefault(chunk.source_key, {"metric": column, "points": {}, "raw": []})
        for row in body["rows"]:
            moment = chunk.chunk_start + timedelta(seconds=row[0])
            if not start <= moment < end:
                continue
            value = row[index] if index is not None else None
            if resolution == "raw":
                entry["raw"].append([moment.isoformat(), row[1], *row[2:]])
                continue
            key = _bucket(moment, resolution)
            bucket = entry["points"].setdefault(key, [0, 0.0])
            if isinstance(value, (int, float)):
                bucket[0] += 1
                bucket[1] += value
    result = []
    for source_key, entry in sources.items():
        if resolution == "raw":
            points = entry["raw"][:max_points]
        else:
            points = [[moment.isoformat(), round(total / count, 2) if count else None, count]
                      for moment, (count, total) in sorted(entry["points"].items())][:max_points]
        result.append({"source_key": source_key, "metric": entry["metric"], "points": points})
    return {"data_type": data_type, "resolution": resolution, "sources": result,
            "columns": ["time", "duration_s", "..."] if resolution == "raw" else ["time", "mean", "samples"]}
