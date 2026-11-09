"""Analytics Engine: hàm thuần trên các dòng theo ngày (DailyHealthRead hoặc bất kỳ đối tượng cùng thuộc tính).

Mỗi chỉ số của ngày được đánh giá được so với đường nền 28 ngày đã trọn *trước ngày đo* của chính
người dùng (trung vị + MAD, baseline.robust). HRV được so trên thang log vì phân phối lệch phải
(Plews và cs., 2013). Không có giá trị thì trạng thái độ phủ nói vì sao; không bao giờ điền 0.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from domains.analytics.schemas.daily_health import (
    DataQuality,
    LoadSummary,
    MetricReading,
    SleepDetail,
    SleepNight,
    SleepWeek,
    Trend,
)
from domains.analytics.services.coverage import day_state
from domains.analytics.services.daily_health.baseline import Robust, robust

BASELINE_DAYS = 28
TREND_DAYS = 7
# Đủ để gọi là một đường nền; dưới mức này độ lệch không được tính.
MIN_BASELINE_DAYS = 7
# Đồng bộ thành công gần nhất cũ hơn chừng này thì dữ liệu "hôm nay" có thể chưa về.
STALE_AFTER_HOURS = 24
# Thay đổi nhỏ nhất đáng kể = 0,5 × độ lệch chuẩn của nền (smallest worthwhile change; Hopkins 2004, Plews 2013).
SWC_FACTOR = 0.5
# ACWR chỉ có nghĩa khi đã có chừng này ngày nhật ký tải (tải mãn tính là trung bình 4 tuần).
MIN_LOAD_HISTORY_DAYS = 21


@dataclass(frozen=True)
class MetricSpec:
    column: str
    label: str
    unit: str
    data_type: str
    # Sàn độ phân tán (cùng thang so sánh) để MAD = 0 không làm z bùng nổ.
    floor: float
    log: bool = False
    # Chỉ số "lõi" của độ sẵn sàng: giấc ngủ, HRV, nhịp tim nghỉ.
    core: bool = False
    # Ngày được đọc so với ngày đánh giá: 0 = chính ngày đó (giấc ngủ chốt theo ngày thức dậy), -1 = hôm qua (tổng cả ngày).
    offset: int = 0
    # Cho phép lấy hôm trước khi ngày đó chưa có: chỉ cho chỉ số tính theo cả ngày lịch (nhịp tim nghỉ),
    # không cho chỉ số của đêm qua (giấc ngủ, HRV, SpO2...), vì giá trị đêm trước không nói gì về đêm nay.
    fallback: bool = False
    provider_relative: bool = False


METRICS = (
    MetricSpec("sleep_minutes", "Giấc ngủ đêm qua", "min", "sleep", floor=20, core=True),
    MetricSpec("hrv_ms", "HRV", "ms", "daily-heart-rate-variability", floor=0.05, log=True, core=True),
    MetricSpec("resting_hr_bpm", "Nhịp tim nghỉ", "bpm", "daily-resting-heart-rate", floor=1.0, core=True, fallback=True),
    MetricSpec("spo2_avg_pct", "SpO2 trung bình", "%", "daily-oxygen-saturation", floor=0.5),
    MetricSpec("respiratory_rate", "Nhịp thở khi ngủ", "breaths/min", "daily-respiratory-rate", floor=0.3),
    MetricSpec("skin_temp_delta_c", "Chênh nhiệt độ da khi ngủ", "°C", "daily-sleep-temperature-derivations",
               floor=0.1, provider_relative=True),
    MetricSpec("steps", "Bước chân hôm qua", "steps", "steps", floor=500, offset=-1),
    MetricSpec("active_zone_minutes", "Phút vùng tim hôm qua", "min", "active-zone-minutes", floor=5, offset=-1),
)
SPECS = {spec.column: spec for spec in METRICS}
TREND_METRICS = ("hrv_ms", "resting_hr_bpm", "sleep_minutes", "steps")


def _value(row: Any, column: str) -> float | None:
    value = getattr(row, column, None) if row is not None else None
    return float(value) if value is not None else None


def _scaled(value: float, spec: MetricSpec) -> float | None:
    if spec.log:
        return math.log(value) if value > 0 else None
    return value


def _window(by_day: dict[date, Any], column: str, end: date, days: int) -> list[float]:
    """Giá trị của `days` ngày kết thúc ở `end` (tính cả end)."""
    values = (_value(by_day.get(end - timedelta(days=offset)), column) for offset in range(days))
    return [value for value in values if value is not None]


def baseline(by_day: dict[date, Any], spec: MetricSpec, measured_on: date) -> tuple[Robust, Robust]:
    """(nền theo đơn vị gốc, nền trên thang so sánh) của 28 ngày trước ngày đo."""
    values = _window(by_day, spec.column, measured_on - timedelta(days=1), BASELINE_DAYS)
    scaled = [x for x in (_scaled(value, spec) for value in values) if x is not None]
    return robust(values), robust(scaled)


def deviation(value: float | None, raw: Robust, scaled: Robust, spec: MetricSpec) -> dict[str, float | None]:
    if value is None or raw.median is None or raw.n < MIN_BASELINE_DAYS:
        return {"delta": None, "delta_pct": None, "z": None}
    delta = value - raw.median
    point = _scaled(value, spec)
    z = None
    if point is not None and scaled.median is not None:
        z = (point - scaled.median) / max(scaled.scale or 0.0, spec.floor)
    return {"delta": round(delta, 2), "delta_pct": round(100 * delta / raw.median, 1) if raw.median else None,
            "z": round(z, 2) if z is not None else None}


def readings(day: date, by_day: dict[date, Any], availability: dict[str, Any]) -> list[MetricReading]:
    found = []
    for spec in METRICS:
        target = day + timedelta(days=spec.offset)
        measured_on, value = target, _value(by_day.get(target), spec.column)
        if value is None and spec.fallback:
            previous = _value(by_day.get(target - timedelta(days=1)), spec.column)
            if previous is not None:
                measured_on, value = target - timedelta(days=1), previous
        raw, scaled = baseline(by_day, spec, measured_on)
        found.append(MetricReading(
            metric=spec.column, label=spec.label, unit=spec.unit, value=round(value, 2) if value is not None else None,
            measured_on=measured_on if value is not None else None,
            state=day_state(value, spec.column, availability.get(spec.data_type), target),
            baseline=round(raw.median, 2) if raw.median is not None and raw.n >= MIN_BASELINE_DAYS else None,
            baseline_mad=round(raw.mad, 2) if raw.mad is not None and raw.n >= MIN_BASELINE_DAYS else None,
            baseline_n=raw.n, provider_relative=spec.provider_relative, **deviation(value, raw, scaled, spec)))
    return found


def trends(day: date, by_day: dict[date, Any]) -> list[Trend]:
    """7 ngày gần nhất so với 28 ngày trước đó; chiều chỉ được nêu khi vượt thay đổi nhỏ nhất đáng kể."""
    found = []
    for column in TREND_METRICS:
        spec = SPECS[column]
        end = day + timedelta(days=spec.offset)
        recent = _window(by_day, column, end, TREND_DAYS)
        earlier = _window(by_day, column, end - timedelta(days=TREND_DAYS), BASELINE_DAYS)
        now, then = robust(recent), robust(earlier)
        direction, delta_pct = "unknown", None
        if now.median is not None and then.median is not None and now.n >= 4 and then.n >= 14:
            delta_pct = round(100 * (now.median - then.median) / then.median, 1) if then.median else None
            scaled_then = robust(x for x in (_scaled(value, spec) for value in earlier) if x is not None)
            scaled_now = robust(x for x in (_scaled(value, spec) for value in recent) if x is not None)
            change = (scaled_now.median or 0.0) - (scaled_then.median or 0.0)
            threshold = SWC_FACTOR * max(scaled_then.scale or 0.0, spec.floor)
            direction = "up" if change >= threshold else "down" if change <= -threshold else "flat"
        found.append(Trend(metric=column, label=spec.label, unit=spec.unit,
                           recent=round(now.median, 1) if now.median is not None else None, recent_n=now.n,
                           baseline=round(then.median, 1) if then.median is not None else None, baseline_n=then.n,
                           delta_pct=delta_pct, direction=direction))
    return found


def _main_sleeps(sessions: Iterable[Any]) -> dict[date, Any]:
    """Giấc ngủ chính dài nhất của mỗi ngày thức dậy (bỏ giấc ngủ ngắn ban ngày)."""
    nights: dict[date, Any] = {}
    for night in sessions:
        if getattr(night, "is_nap", False):
            continue
        current = nights.get(night.local_date)
        if current is None or (night.minutes_asleep or 0) > (current.minutes_asleep or 0):
            nights[night.local_date] = night
    return nights


def _pct(part: Any, whole: float | None) -> float | None:
    return round(100 * float(part) / whole, 1) if part is not None and whole else None


def _sd(values: list[float]) -> float | None:
    return round(statistics.pstdev(values), 0) if len(values) >= 4 else None


def sleep_detail(day: date, sessions: Iterable[Any], zone: str, need_minutes: int) -> SleepDetail:
    """Đêm qua (giờ ngủ, hiệu quả, giai đoạn) và 7 đêm (nợ ngủ, độ đều giờ ngủ/giờ dậy).

    Giờ đi ngủ được đo bằng phút kể từ 12:00 trưa hôm trước để 23:30 và 00:30 đứng cạnh nhau, không
    cách nhau 23 giờ. Thiết bị không có giai đoạn (ghi tay, kiểu classic) thì phần trăm giai đoạn là None.
    """
    tz = ZoneInfo(zone)
    nights = _main_sleeps(sessions)
    last = nights.get(day)
    last_night = None
    if last is not None:
        bed, wake = last.start_at.astimezone(tz), last.end_at.astimezone(tz)
        staged = sum(x or 0 for x in (last.deep_minutes, last.rem_minutes, last.light_minutes)) or None
        last_night = SleepNight(
            date=day, bedtime=bed.strftime("%H:%M"), wake_time=wake.strftime("%H:%M"),
            minutes_asleep=last.minutes_asleep, minutes_in_bed=last.minutes_in_period,
            efficiency_pct=float(last.efficiency_pct) if last.efficiency_pct is not None else None,
            minutes_to_fall_asleep=last.minutes_to_fall_asleep, minutes_awake=last.minutes_awake,
            deep_minutes=last.deep_minutes, rem_minutes=last.rem_minutes, light_minutes=last.light_minutes,
            deep_pct=_pct(last.deep_minutes, staged), rem_pct=_pct(last.rem_minutes, staged),
            light_pct=_pct(last.light_minutes, staged),
            manual=bool((getattr(last, "data_source", None) or {}).get("manual")))
    week = [nights[d] for d in (day - timedelta(days=offset) for offset in range(TREND_DAYS)) if d in nights]
    asleep = [float(night.minutes_asleep) for night in week if night.minutes_asleep is not None]
    bedtimes, wakes = [], []
    for night in week:
        bed, wake = night.start_at.astimezone(tz), night.end_at.astimezone(tz)
        noon = datetime.combine(bed.date() if bed.hour >= 12 else bed.date() - timedelta(days=1),
                                datetime.min.time(), tz).replace(hour=12)
        bedtimes.append((bed - noon).total_seconds() / 60)
        wakes.append(wake.hour * 60 + wake.minute)
    debt = round(sum(max(0.0, need_minutes - value) for value in asleep)) if len(asleep) >= 4 else None
    return SleepDetail(last_night=last_night, week=SleepWeek(
        nights=len(week), need_minutes=need_minutes,
        avg_minutes_asleep=round(statistics.fmean(asleep), 0) if asleep else None, debt_minutes=debt,
        bedtime_sd_minutes=_sd(bedtimes), wake_sd_minutes=_sd(wakes)))


def load_summary(day: date, loads: dict[date, Decimal], missing_rpe: int) -> LoadSummary | None:
    """ACWR trung bình trượt tính đến hôm qua (buổi hôm nay có thể chưa tập), dùng chung với phân tích huấn luyện."""
    from domains.training.services.training_analytics import _acwr

    if not loads:
        return None
    yesterday = day - timedelta(days=1)
    acute, chronic, ratio = _acwr(loads, yesterday)
    # Tải mãn tính 28 ngày bị tính thiếu khi nhật ký mới bắt đầu, làm ACWR phồng lên: chưa đủ lịch sử thì không nêu.
    if (yesterday - min(loads)).days + 1 < MIN_LOAD_HISTORY_DAYS:
        ratio = None
    value = loads.get(yesterday)
    return LoadSummary(yesterday=float(value) if value is not None else None, acute_7d=float(acute),
                       chronic_weekly=round(float(chronic), 1), acwr=ratio, sessions_without_rpe=missing_rpe)


def quality(readings_: Iterable[MetricReading], status: Any, now: datetime) -> DataQuality:
    readings_ = list(readings_)
    last = getattr(status, "last_success_at", None) if status is not None else None
    connected = bool(status is not None and getattr(status, "connected", False))
    stale = (not connected) or last is None or (now - last) > timedelta(hours=STALE_AFTER_HOURS)
    core = [reading for reading in readings_ if SPECS[reading.metric].core]
    return DataQuality(connected=connected, last_sync_at=last, stale=stale,
                       missing=[reading.metric for reading in readings_ if reading.value is None],
                       baseline_days=min((reading.baseline_n for reading in core if reading.value is not None), default=0))
