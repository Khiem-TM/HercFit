"""Đánh giá sức khoẻ hằng ngày (GET /api/v2/health/daily-assessment).

Mọi con số do backend tính tất định từ health_points và nhật ký tập; trợ lý chỉ diễn giải.
Thiếu dữ liệu được nêu bằng trạng thái độ phủ, không bao giờ thành số 0 hay "bình thường".
"""
from datetime import date as Date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ReadinessState = Literal["ready", "steady", "ease_off", "recover", "needs_review", "insufficient_data"]
Confidence = Literal["high", "medium", "low"]
# info: quan sát đáng nêu nhưng không đổi trạng thái (giờ ngủ thất thường, hiệu quả ngủ thấp, ngủ ghi tay).
ReasonKind = Literal["strain", "positive", "data", "review", "info"]
Direction = Literal["up", "down", "flat", "unknown"]


class MetricReading(BaseModel):
    """Giá trị của một chỉ số trong ngày được đánh giá so với đường nền cá nhân trước ngày đo."""
    metric: str
    label: str
    unit: str
    value: float | None = None
    # Ngày của giá trị (có thể là hôm trước khi hôm nay chưa có, ví dụ nhịp tim nghỉ tính vào cuối ngày).
    measured_on: Date | None = None
    # Trạng thái độ phủ (OBSERVED, ZERO, NO_DATA, NOT_SYNCED, NOT_GRANTED, UNSUPPORTED).
    state: str
    baseline: float | None = None
    baseline_mad: float | None = None
    baseline_n: int = 0
    delta: float | None = None
    delta_pct: float | None = None
    # Độ lệch chuẩn hoá bền (trên log với HRV); None khi chưa đủ nền.
    z: float | None = None
    # Giá trị nhà cung cấp đã tự so với nền của nó (vd. chênh nhiệt độ da khi ngủ): dùng lại, không tính lại.
    provider_relative: bool = False


class Trend(BaseModel):
    metric: str
    label: str
    unit: str
    recent: float | None = None
    recent_n: int = 0
    baseline: float | None = None
    baseline_n: int = 0
    delta_pct: float | None = None
    direction: Direction = "unknown"


class SleepNight(BaseModel):
    """Giấc ngủ chính của đêm kết thúc vào ngày được đánh giá (giờ theo múi giờ của người dùng)."""
    date: Date
    bedtime: str
    wake_time: str
    minutes_asleep: int | None = None
    minutes_in_bed: int | None = None
    efficiency_pct: float | None = None
    minutes_to_fall_asleep: int | None = None
    minutes_awake: int | None = None
    deep_minutes: int | None = None
    rem_minutes: int | None = None
    light_minutes: int | None = None
    deep_pct: float | None = None
    rem_pct: float | None = None
    light_pct: float | None = None
    # Người dùng ghi tay (giờ ngủ–giờ dậy, không có giai đoạn), không phải thiết bị đo.
    manual: bool = False


class SleepWeek(BaseModel):
    """7 đêm kết thúc vào ngày được đánh giá; đêm không có dữ liệu là chưa biết, không tính là thiếu ngủ."""
    nights: int
    need_minutes: int
    avg_minutes_asleep: float | None = None
    # Tổng phần ngủ thiếu so với mức khuyến nghị tối thiểu theo tuổi, chỉ trên các đêm có dữ liệu.
    debt_minutes: int | None = None
    bedtime_sd_minutes: float | None = None
    wake_sd_minutes: float | None = None


class SleepDetail(BaseModel):
    last_night: SleepNight | None = None
    week: SleepWeek


class LoadSummary(BaseModel):
    """Tải tập từ nhật ký HercFit (sRPE); buổi thiết bị không có RPE không vào tải."""
    yesterday: float | None = None
    acute_7d: float
    chronic_weekly: float
    acwr: float | None = None
    sessions_without_rpe: int = 0


class DataQuality(BaseModel):
    connected: bool
    last_sync_at: datetime | None = None
    stale: bool
    missing: list[str]
    baseline_days: int


class Reason(BaseModel):
    code: str
    kind: ReasonKind
    metric: str | None = None
    value: float | None = None
    baseline: float | None = None
    unit: str | None = None
    delta: float | None = None
    text: str


class Recommendation(BaseModel):
    code: str
    text: str


class DailyAssessmentRead(BaseModel):
    date: Date
    timezone: str
    algorithm_version: str
    state: ReadinessState
    label: str
    # 0–100, None khi needs_review / insufficient_data (readiness.score).
    score: int | None = None
    confidence: Confidence
    summary: str
    reasons: list[Reason]
    recommendations: list[Recommendation]
    metrics: list[MetricReading]
    trends: list[Trend]
    sleep: SleepDetail | None = None
    load: LoadSummary | None = None
    data_quality: DataQuality
    method: str
    disclaimer: str
