"""Số đo cơ thể từ hai nguồn: nhập tay trong HercFit (body_metrics) và Google Health (health_points).

Khi đã kết nối Google, cân nặng / chiều cao / mỡ cơ thể được ghi thẳng lên Google và đọc về
bằng reconcile; body_metrics giữ số đo nhập khi chưa kết nối và các chỉ số Google không có
(khối cơ, vòng eo...). Mỗi mẫu Google là một `Reading` có cùng tên trường với BodyMetricRead.

Một lần cân thấy hai lần (gõ tay và cân thông minh trong vòng 10 phút, lệch ≤ 0,2 kg) chỉ tính
một lần trong xu hướng; giữ bản nhập tay (người dùng đã xác nhận nó).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select

SAME_WEIGHIN_SECONDS = 10 * 60
SAME_WEIGHIN_KG = 0.2
FIELDS = {"weight_kg": "weight", "height_cm": "height", "body_fat_pct": "body-fat"}


@dataclass
class Reading:
    id: UUID
    user_id: UUID
    recorded_at: datetime
    created_at: datetime
    updated_at: datetime
    weight_kg: Decimal | None = None
    height_cm: Decimal | None = None
    body_fat_pct: Decimal | None = None
    muscle_mass_kg: Decimal | None = None
    additional_metrics: dict[str, Any] = field(default_factory=dict)
    source: str = "GOOGLE_HEALTH"
    version_id: int = 1
    is_active: bool = True
    written_by_hercfit: bool = False


async def google(session, user_id: UUID, recorded_from: datetime | None = None, recorded_to: datetime | None = None,
                 *, limit: int = 200, field: str | None = None, respect_consent: bool = True) -> list[Reading]:
    """Mẫu Google mới nhất trước. Số đo của thiết bị (cân thông minh...) chỉ hiện với trợ lý khi người
    dùng cho phép dùng dữ liệu thiết bị; số đo người dùng ghi qua HercFit luôn là của họ (MANUAL)."""
    from domains.health_records.models.health_points import HealthPoint
    from domains.health_records.views import body_value
    from domains.identity.consent import device_access

    types = [FIELDS[field]] if field else list(FIELDS.values())
    query = select(HealthPoint).where(HealthPoint.user_id == user_id, HealthPoint.data_type.in_(types))
    if respect_consent and not await device_access(session, user_id):
        query = query.where(HealthPoint.written_by_hercfit.is_(True))
    if recorded_from is not None:
        query = query.where(HealthPoint.start_at >= recorded_from)
    if recorded_to is not None:
        query = query.where(HealthPoint.start_at <= recorded_to)
    points = (await session.execute(query.order_by(HealthPoint.start_at.desc()).limit(limit))).scalars()
    readings = []
    for point in points:
        if (measured := body_value(point)) is None:
            continue
        column, value = measured
        readings.append(Reading(id=point.id, user_id=user_id, recorded_at=point.start_at, created_at=point.created_at,
                                updated_at=point.updated_at, written_by_hercfit=point.written_by_hercfit,
                                source="MANUAL" if point.written_by_hercfit else "GOOGLE_HEALTH",
                                **{column: Decimal(str(value))}))
    return readings


def _same(a: Any, b: Any) -> bool:
    return (abs((a.recorded_at - b.recorded_at).total_seconds()) <= SAME_WEIGHIN_SECONDS
            and abs(float(a.weight_kg) - float(b.weight_kg)) <= SAME_WEIGHIN_KG)


def distinct_weighins(metrics: Iterable[Any]) -> list[Any]:
    """Các số đo có cân nặng, mỗi lần cân một số đo, theo thứ tự đầu vào."""
    weighed = [metric for metric in metrics if metric.weight_kg is not None]
    kept: list[Any] = []
    for metric in sorted(weighed, key=lambda item: item.recorded_at):
        twin = next((index for index in range(len(kept) - 1, -1, -1) if _same(metric, kept[index])), None)
        if twin is None:
            kept.append(metric)
        elif metric.source == "MANUAL" and kept[twin].source != "MANUAL":
            kept[twin] = metric
    chosen = {id(metric) for metric in kept}
    return [metric for metric in weighed if id(metric) in chosen]
