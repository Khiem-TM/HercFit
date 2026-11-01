"""Số đo cơ thể cho xu hướng.

Bộ đọc v2 `body`: một lần cân được ghi hai lần, người dùng gõ tay và đồng bộ từ
cân, chỉ tính một lần. Các số đo cách nhau trong 10 phút và 0,2 kg là một
lần cân; giữ bản nhập tay (người dùng đã xác nhận nó), nếu không thì giữ bản sớm nhất.
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
    """Các số đo có cân nặng, mỗi lần cân một số đo, theo thứ tự đầu vào (với bộ đọc v1 thì lấy tất cả)."""
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
