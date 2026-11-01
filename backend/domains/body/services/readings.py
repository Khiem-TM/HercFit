"""Body readings for trends.

Reader v2 `body`: a weigh-in recorded twice, typed by the user and synced from a
scale, counts once. Readings within 10 minutes and 0.2 kg of each other are one
weigh-in; the manual reading is kept (the user confirmed it), otherwise the earliest.
"""
from __future__ import annotations

from typing import Any, Iterable

from core.flags import reader_v2

SAME_WEIGHIN_SECONDS = 10 * 60
SAME_WEIGHIN_KG = 0.2


def _same(a: Any, b: Any) -> bool:
    return (abs((a.recorded_at - b.recorded_at).total_seconds()) <= SAME_WEIGHIN_SECONDS
            and abs(float(a.weight_kg) - float(b.weight_kg)) <= SAME_WEIGHIN_KG)


def distinct_weighins(metrics: Iterable[Any]) -> list[Any]:
    """Metrics with a weight, one per weigh-in, in the input order (all of them under reader v1)."""
    weighed = [metric for metric in metrics if metric.weight_kg is not None]
    if not reader_v2("body"):
        return weighed
    kept: list[Any] = []
    for metric in sorted(weighed, key=lambda item: item.recorded_at):
        twin = next((index for index in range(len(kept) - 1, -1, -1) if _same(metric, kept[index])), None)
        if twin is None:
            kept.append(metric)
        elif metric.source == "MANUAL" and kept[twin].source != "MANUAL":
            kept[twin] = metric
    chosen = {id(metric) for metric in kept}
    return [metric for metric in weighed if id(metric) in chosen]
