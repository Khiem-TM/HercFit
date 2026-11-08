"""Đường nền cá nhân dùng chung: trung vị và MAD trên các ngày đã trọn.

Một chỗ tính duy nhất cho tổng quan sức khoẻ, context API, insights và đánh giá hằng ngày, để
cùng một chỉ số không bao giờ có hai "đường nền" khác nhau. Trung vị và MAD bền với ngày
ngoại lai (đeo lỏng, ốm một hôm) hơn trung bình và độ lệch chuẩn.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Iterable

# MAD × hằng số này ước lượng độ lệch chuẩn khi phân phối gần chuẩn (Rousseeuw & Croux, 1993).
MAD_TO_SD = 1.4826


@dataclass(frozen=True)
class Robust:
    median: float | None
    mad: float | None
    n: int

    @property
    def scale(self) -> float | None:
        """Độ lệch chuẩn ước lượng từ MAD; None khi chưa đủ hai giá trị."""
        return self.mad * MAD_TO_SD if self.mad is not None else None


def robust(values: Iterable[Any]) -> Robust:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return Robust(None, None, 0)
    middle = statistics.median(clean)
    mad = statistics.median(abs(value - middle) for value in clean) if len(clean) > 1 else None
    return Robust(middle, mad, len(clean))


def median(values: Iterable[Any], digits: int = 1) -> float | None:
    found = robust(values).median
    return round(found, digits) if found is not None else None
