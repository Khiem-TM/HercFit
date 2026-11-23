"""Daily Health Intelligence: phân tích sức khoẻ hằng ngày tất định (snapshot, đường nền, độ lệch, độ sẵn sàng).

Các phần trong file, theo thứ tự:
baseline   đường nền cá nhân dùng chung (trung vị + MAD) cho mọi nơi so với "bình thường của bạn"
coverage   độ phủ dữ liệu theo ngày và đường nền 28 ngày cho insights/context API
analytics  hàm thuần: snapshot của ngày, độ lệch so với nền, xu hướng 7 ngày, chất lượng dữ liệu
readiness  luật quyết định có phiên bản: trạng thái sẵn sàng, lý do, độ tin cậy, khuyến nghị
service    đọc health_points/nhật ký tập rồi gọi các hàm thuần (không lưu gì, tính lúc đọc)

LLM không tính lại con số nào ở đây và không chẩn đoán: nó chỉ diễn giải kết quả đã có nguồn.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID
from zoneinfo import ZoneInfo

from domains.analytics.schemas import (
    DailyAssessmentRead,
    DataQuality,
    LoadSummary,
    MetricReading,
    Reason,
    Recommendation,
    SleepDetail,
    SleepNight,
    SleepWeek,
    Trend,
)
from domains.health_records import ports, views
from domains.health_records.schemas import HRV_DROP_PCT, RHR_ELEVATION_BPM, recommended_sleep_hours
from domains.training import services as training_analytics

# --------------------------------------------------------------------------------------------------
# Đường nền cá nhân dùng chung: trung vị và MAD trên các ngày đã trọn.
#
# Một chỗ tính duy nhất cho tổng quan sức khoẻ, context API, insights và đánh giá hằng ngày, để
# cùng một chỉ số không bao giờ có hai "đường nền" khác nhau. Trung vị và MAD bền với ngày
# ngoại lai (đeo lỏng, ốm một hôm) hơn trung bình và độ lệch chuẩn.
# --------------------------------------------------------------------------------------------------

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


# --------------------------------------------------------------------------------------------------
# Độ phủ và đường nền: biết gì, thiếu gì, và vì sao.
#
# Độ phủ theo (ngày, loại dữ liệu) là một trong
#   OBSERVED      có giá trị (hoặc có mẫu dày trong vài giây)
#   ZERO          giá trị đếm được đúng bằng 0 (ví dụ 0 tầng): là dữ liệu, không phải vắng mặt
#   NO_DATA       loại này đã đồng bộ qua ngày đó và không có gì
#   NOT_GRANTED   người dùng chưa cấp scope
#   UNSUPPORTED   HercFit không đọc loại này (registry hoặc kiểm chứng)
#   NOT_SYNCED    ngày đó mới hơn lần đọc trọn vẹn cuối cùng của loại này
# Ít bước không bao giờ có nghĩa là "không đeo": việc đeo không suy ra từ mức hoạt động, chỉ từ
# dữ liệu quan sát được, và được báo là chưa biết khi không có gì hỗ trợ.
#
# Đường nền là trung vị trên các ngày đã trọn trước `as_of`, kèm cỡ mẫu và `algorithm_version`,
# để đổi phương pháp không bao giờ âm thầm đổi câu trả lời cũ. Mọi thứ được tính lúc đọc từ
# health_points (không có bảng cache).
# --------------------------------------------------------------------------------------------------

COVERAGE_ALGORITHM_VERSION = "baseline-median-v1"
# Các cột theo ngày được theo dõi độ phủ, kèm loại dữ liệu nuôi chúng.
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
    algorithm_version: str = COVERAGE_ALGORITHM_VERSION
    # Độ lệch tuyệt đối trung vị (cùng đơn vị với chỉ số): độ phân tán bền với ngày ngoại lai.
    mad: float | None = None


def day_state(value: Any, column: str, availability: ports.TypeAvailability | None, day: date) -> str:
    if availability is None or not availability.enabled:
        return "UNSUPPORTED"
    if not availability.granted:
        return "NOT_GRANTED"
    if value is not None:
        return "ZERO" if column in COUNTED and float(value) == 0 else "OBSERVED"
    if (availability.complete_through is None or day > availability.complete_through
            or (availability.complete_from is not None and day < availability.complete_from)):
        return "NOT_SYNCED"
    return "NO_DATA"


async def daily_rows(session, user_id: UUID, start: date, end: date) -> dict[date, Any]:
    return {row.local_date: row for row in await views.daily(session, user_id, start, end)}


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


async def baselines(session, user_id: UUID, as_of: date, window_days: int = 28) -> dict[str, Baseline]:
    rows = await daily_rows(session, user_id, as_of - timedelta(days=window_days), as_of - timedelta(days=1))
    result = {}
    for metric in BASELINE_METRICS:
        values = [float(getattr(row, metric)) for row in rows.values() if getattr(row, metric) is not None]
        found = robust(values)
        result[metric] = Baseline(
            metric=metric, value=round(found.median, 2) if found.median is not None else None,
            spread=round(statistics.pstdev(values), 2) if len(values) > 1 else None, n=found.n,
            window_days=window_days, as_of=as_of, mad=round(found.mad, 2) if found.mad is not None else None)
    return result


async def baselines_for(session, user_id: UUID, end: date, window_days: int,
                        today: date | None = None) -> dict[str, Baseline]:
    """Đường nền cho một báo cáo kết thúc ở `end`: chỉ các ngày đã trọn (trước hôm nay)."""
    from datetime import datetime, timezone

    today = today or datetime.now(timezone.utc).date()
    return await baselines(session, user_id, min(end + timedelta(days=1), today), window_days)


# --------------------------------------------------------------------------------------------------
# Analytics Engine: hàm thuần trên các dòng theo ngày (DailyHealthRead hoặc bất kỳ đối tượng cùng thuộc tính).
#
# Mỗi chỉ số của ngày được đánh giá được so với đường nền 28 ngày đã trọn *trước ngày đo* của chính
# người dùng (trung vị + MAD, baseline.robust). HRV được so trên thang log vì phân phối lệch phải
# (Plews và cs., 2013). Không có giá trị thì trạng thái độ phủ nói vì sao; không bao giờ điền 0.
# --------------------------------------------------------------------------------------------------

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
    from domains.training.services import _acwr

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


# --------------------------------------------------------------------------------------------------
# Readiness Decision Engine: luật tất định, có phiên bản, giải thích được.
#
# Đây là một heuristic thăm dò để gợi ý cường độ tập, KHÔNG phải công cụ đã được kiểm định lâm sàng và
# không chẩn đoán gì. Căn cứ:
# * có bằng chứng: điều chỉnh tập theo HRV so với nền cá nhân (Kiviniemi và cs., 2007; Plews và cs., 2013);
#   thời lượng ngủ khuyến nghị theo tuổi (National Sleep Foundation, Hirshkowitz và cs., 2015);
# * heuristic chọn cho HercFit (cần đánh giá thêm): ngưỡng z, 45 phút ngủ hụt, 5 bpm nhịp tim nghỉ (đã dùng ở
#   tổng quan sức khoẻ), ACWR > 1,5 (Gabbett, 2016; khái niệm bị phê bình bởi Impellizzeri và cs., 2020),
#   nợ ngủ 5 giờ/7 đêm (hậu quả cộng dồn của ngủ thiếu: Van Dongen và cs., 2003), độ lệch giờ ngủ 60 phút
#   (độ đều giấc ngủ: Phillips và cs., 2017), hiệu quả ngủ 85%.
# Mọi ngưỡng nằm trong THRESHOLDS để đổi phương pháp là đổi phiên bản, không âm thầm đổi câu trả lời cũ.
# --------------------------------------------------------------------------------------------------

# v2: thêm phân tích giấc ngủ (nợ ngủ 7 đêm, độ đều giờ ngủ, hiệu quả, ngủ ghi tay).
# v3: thêm điểm sẵn sàng 0–100 (SCORE), suy ra từ cùng các độ lệch; trạng thái không đổi.
ALGORITHM_VERSION = "readiness-heuristic-v3"
THRESHOLDS = {
    "sleep_short_vs_baseline_min": 45,     # ngủ ít hơn nền cá nhân chừng này phút (và dưới khuyến nghị)
    "sleep_short_no_baseline_min": 60,     # khi chưa có nền: thấp hơn mức khuyến nghị tối thiểu chừng này phút
    "rhr_elevated_bpm": RHR_ELEVATION_BPM,  # cao hơn nền ≥ 5 bpm
    "rhr_low_z": -1.0,                     # thấp hơn nền ≥ 1 SD: tín hiệu tích cực
    # HRV một ngày rất nhiễu (Plews và cs., 2013 khuyên dùng trung bình trượt 7 ngày): chỉ một lần giảm rất mạnh
    # (≥ 2 SD) mới đủ; còn lại cần xu hướng 7 ngày. Bản nháp dùng −1 SD cho 29% báo nhầm trong backtest mô phỏng.
    "hrv_low_z": -2.0,                     # ln HRV hôm nay thấp hơn nền ≥ 2 SD
    "hrv_high_z": 0.5,                     # ln HRV cao hơn nền ≥ 0,5 SD (vượt thay đổi nhỏ nhất đáng kể)
    "hrv_trend_drop_pct": HRV_DROP_PCT,    # trung vị 7 ngày thấp hơn nền ≥ 15%
    "acwr_high": 1.5,                      # training_analytics.ACWR_DANGER
    "review_z": 3.0,                       # lệch rất mạnh so với nền của chính người dùng
    "review_skin_temp_c": 1.0,             # chênh nhiệt độ da (nhà cung cấp đã so với nền của nó)
    "review_spo2_pct": 90.0,               # SpO2 trung bình đêm dưới mức này: chỉ hiển thị, khuyên kiểm tra
    "sleep_debt_min": 300,                 # nợ ngủ 7 đêm (phút) so với mức khuyến nghị tối thiểu
    "sleep_debt_min_nights": 4,            # cần ít nhất chừng này đêm có dữ liệu mới nói về nợ ngủ
    "bedtime_sd_min": 60,                  # độ lệch chuẩn giờ đi ngủ (phút): lịch ngủ thất thường
    "efficiency_low_pct": 85.0,            # hiệu quả giấc ngủ (ngủ / trên giường)
    "high_confidence_days": 21,
    "medium_confidence_days": 14,
}
# Điểm 0–100 chỉ là cách đọc nhanh của trạng thái, không phải chỉ số sinh lý: 70 = đúng nền của bạn,
# mỗi độ lệch chuẩn (theo hướng tốt) cộng/trừ 10 điểm, trung bình có trọng số trên các chỉ số có nền;
# tín hiệu căng thẳng không gắn với ba chỉ số này (tải tăng nhanh, nợ ngủ) trừ thêm. Kết quả luôn được kẹp
# vào khoảng của trạng thái, để điểm và nhãn không bao giờ nói hai điều khác nhau.
SCORE = {
    "base": 70,
    "points_per_sd": 10,
    "weights": {"hrv_ms": 0.4, "resting_hr_bpm": 0.3, "sleep_minutes": 0.3},
    "z_clip": 3.0,
    "sleep_z_max": 1.0,            # ngủ nhiều hơn nền không làm "sẵn sàng hơn" quá một độ lệch
    "other_strain_penalty": 6,
    "bands": {"ready": (70, 100), "steady": (55, 85), "ease_off": (35, 69), "recover": (0, 49)},
}
LABELS = {"ready": "Sẵn sàng", "steady": "Ổn định", "ease_off": "Nên giảm nhẹ", "recover": "Ưu tiên hồi phục",
          "needs_review": "Cần xem lại", "insufficient_data": "Chưa đủ dữ liệu"}
RECOMMENDATIONS = {
    "train_as_planned": "Có thể tập theo kế hoạch, kể cả buổi cường độ cao nếu đã lên lịch.",
    "train_listen": "Tập theo kế hoạch và lắng nghe cơ thể.",
    "reduce_intensity": "Cân nhắc giảm cường độ hoặc khối lượng hôm nay (ví dụ đổi buổi nặng sang buổi nhẹ).",
    "prioritize_recovery": "Ưu tiên hồi phục: nghỉ hoặc vận động nhẹ, ngủ đủ và uống đủ nước.",
    "check_with_professional": "Kiểm tra lại cách đeo thiết bị; nếu có triệu chứng (sốt, đau ngực, khó thở, mệt bất thường) "
                               "hãy hỏi ý kiến nhân viên y tế.",
    "sync_device": "Đeo thiết bị khi ngủ và đồng bộ Google Health để có dữ liệu đánh giá.",
    "sleep_earlier": "Ưu tiên ngủ sớm và đủ giấc tối nay.",
    "hold_load": "Tải 7 ngày tăng nhanh: giữ hoặc giảm tải vài ngày tới.",
    "repay_sleep": "Bù nợ ngủ dần: ngủ sớm hơn 30–60 phút trong vài đêm tới, tránh dồn hết vào một đêm.",
    "regular_schedule": "Giữ giờ đi ngủ và thức dậy đều đặn hơn, kể cả cuối tuần.",
    "log_sleep": "Thiết bị không ghi giấc ngủ đêm qua? Bạn có thể ghi tay giờ ngủ và giờ dậy.",
}
DISCLAIMER = ("Đánh giá độ sẵn sàng tập luyện theo heuristic từ dữ liệu thiết bị so với nền của chính bạn; "
              "không phải chẩn đoán y khoa.")
METHOD = (f"{ALGORITHM_VERSION}: đường nền trung vị/MAD 28 ngày đã trọn trước ngày đo, HRV so trên thang log, "
          "luật trạng thái tất định; điểm 0–100 = 70 + 10 × độ lệch có trọng số, kẹp theo trạng thái; "
          "các ngưỡng là heuristic thăm dò.")
CORE = ("sleep_minutes", "hrv_ms", "resting_hr_bpm")
# Độ sẵn sàng nói về đêm qua: cần ít nhất giấc ngủ hoặc HRV của đêm đó, có đường nền.
NIGHT = ("sleep_minutes", "hrv_ms")
PHYSIOLOGICAL = {"SLEEP_SHORT", "RHR_ELEVATED", "HRV_LOW"}


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "?"
    if unit == "min":
        return f"{int(value) // 60}h{int(value) % 60:02d}"
    return f"{value:g} {unit}"


def _reason(code: str, kind: str, reading: MetricReading | None, text: str) -> Reason:
    if reading is None:
        return Reason(code=code, kind=kind, text=text)
    return Reason(code=code, kind=kind, metric=reading.metric, value=reading.value, baseline=reading.baseline,
                  unit=reading.unit, delta=reading.delta, text=text)


def _sleep_signals(sleep: SleepDetail | None) -> list[Reason]:
    if sleep is None:
        return []
    found, week, night = [], sleep.week, sleep.last_night
    if (week.debt_minutes is not None and week.nights >= THRESHOLDS["sleep_debt_min_nights"]
            and week.debt_minutes >= THRESHOLDS["sleep_debt_min"]):
        found.append(Reason(code="SLEEP_DEBT", kind="strain", metric="sleep_debt", value=week.debt_minutes,
                            baseline=THRESHOLDS["sleep_debt_min"], unit="min",
                            text=f"Nợ ngủ {_fmt(week.debt_minutes, 'min')} trong {week.nights} đêm gần nhất "
                                 f"(so với tối thiểu {_fmt(week.need_minutes, 'min')} mỗi đêm)"))
    if week.bedtime_sd_minutes is not None and week.bedtime_sd_minutes >= THRESHOLDS["bedtime_sd_min"]:
        found.append(Reason(code="SLEEP_IRREGULAR", kind="info", metric="bedtime_sd", value=week.bedtime_sd_minutes,
                            unit="min", text=f"Giờ đi ngủ lệch khoảng ±{week.bedtime_sd_minutes:g} phút giữa các đêm"))
    if night is not None and night.efficiency_pct is not None and not night.manual \
            and night.efficiency_pct < THRESHOLDS["efficiency_low_pct"]:
        found.append(Reason(code="SLEEP_EFFICIENCY_LOW", kind="info", metric="sleep_efficiency",
                            value=night.efficiency_pct, baseline=THRESHOLDS["efficiency_low_pct"], unit="%",
                            text=f"Hiệu quả giấc ngủ {night.efficiency_pct:g}% (dưới {THRESHOLDS['efficiency_low_pct']:g}%)"))
    if night is not None and night.manual:
        found.append(Reason(code="SLEEP_MANUAL", kind="info", metric="sleep_minutes",
                            text="Giấc ngủ đêm qua do bạn ghi tay (không có giai đoạn ngủ, nhịp tim hay HRV)"))
    return found


def signals(readings: Iterable[MetricReading], trends: Iterable[Trend], load: LoadSummary | None,
            quality: DataQuality, age: int | None, sleep_detail: SleepDetail | None = None) -> list[Reason]:
    by = {reading.metric: reading for reading in readings}
    trend = {item.metric: item for item in trends}
    found: list[Reason] = []
    usable = lambda reading: reading is not None and reading.value is not None  # noqa: E731

    sleep = by.get("sleep_minutes")
    if usable(sleep):
        low, high = recommended_sleep_hours(age)
        below_target = sleep.value < low * 60
        if sleep.baseline is not None:
            short = below_target and sleep.value <= sleep.baseline - THRESHOLDS["sleep_short_vs_baseline_min"]
        else:
            short = sleep.value < low * 60 - THRESHOLDS["sleep_short_no_baseline_min"]
        if short:
            found.append(_reason("SLEEP_SHORT", "strain", sleep,
                                 f"Ngủ {_fmt(sleep.value, 'min')}, dưới mức khuyến nghị {low:g}h"
                                 + (f" và ít hơn nền của bạn ({_fmt(sleep.baseline, 'min')})" if sleep.baseline else "")))
        elif low * 60 <= sleep.value <= high * 60:
            found.append(_reason("SLEEP_ON_TARGET", "positive", sleep,
                                 f"Ngủ {_fmt(sleep.value, 'min')}, trong khoảng khuyến nghị {low:g}–{high:g}h"))

    rhr = by.get("resting_hr_bpm")
    if usable(rhr) and rhr.delta is not None:
        if rhr.delta >= THRESHOLDS["rhr_elevated_bpm"]:
            found.append(_reason("RHR_ELEVATED", "strain", rhr,
                                 f"Nhịp tim nghỉ {rhr.value:g} bpm, cao hơn nền {rhr.baseline:g} bpm "
                                 f"(+{rhr.delta:g} bpm)"))
        elif rhr.z is not None and rhr.z <= THRESHOLDS["rhr_low_z"]:
            found.append(_reason("RHR_BELOW", "positive", rhr,
                                 f"Nhịp tim nghỉ {rhr.value:g} bpm, thấp hơn nền {rhr.baseline:g} bpm"))

    hrv = by.get("hrv_ms")
    hrv_trend = trend.get("hrv_ms")
    trend_low = (hrv_trend is not None and hrv_trend.delta_pct is not None and hrv_trend.direction == "down"
                 and hrv_trend.delta_pct <= -THRESHOLDS["hrv_trend_drop_pct"])
    if usable(hrv) and hrv.z is not None:
        if hrv.z <= THRESHOLDS["hrv_low_z"] or trend_low:
            detail = (f"HRV {hrv.value:g} ms, thấp hơn nền {hrv.baseline:g} ms" if hrv.z <= THRESHOLDS["hrv_low_z"]
                      else f"HRV 7 ngày ({hrv_trend.recent:g} ms) thấp hơn nền {abs(hrv_trend.delta_pct):g}%")
            found.append(_reason("HRV_LOW", "strain", hrv, detail))
        elif hrv.z >= THRESHOLDS["hrv_high_z"]:
            found.append(_reason("HRV_ABOVE", "positive", hrv,
                                 f"HRV {hrv.value:g} ms, cao hơn nền {hrv.baseline:g} ms"))

    if load is not None and load.acwr is not None and load.acwr > THRESHOLDS["acwr_high"]:
        found.append(Reason(code="LOAD_HIGH", kind="strain", metric="acwr", value=load.acwr,
                            baseline=THRESHOLDS["acwr_high"],
                            text=f"Tải 7 ngày gấp {load.acwr:g} lần mức trung bình 4 tuần (> {THRESHOLDS['acwr_high']:g})"))

    # Cần xem lại: chỉ hiển thị, không bao giờ là chẩn đoán hay cảnh báo y khoa.
    spo2 = by.get("spo2_avg_pct")
    if usable(spo2) and spo2.value < THRESHOLDS["review_spo2_pct"]:
        found.append(_reason("SPO2_LOW", "review", spo2,
                             f"SpO2 trung bình đêm {spo2.value:g}%, thấp hơn mức thường gặp ({THRESHOLDS['review_spo2_pct']:g}%)"))
    strong = []
    if usable(rhr) and rhr.z is not None and rhr.z >= THRESHOLDS["review_z"]:
        strong.append("nhịp tim nghỉ")
    if usable(hrv) and hrv.z is not None and hrv.z <= -THRESHOLDS["review_z"]:
        strong.append("HRV")
    breathing = by.get("respiratory_rate")
    if usable(breathing) and breathing.z is not None and breathing.z >= THRESHOLDS["review_z"]:
        strong.append("nhịp thở")
    skin = by.get("skin_temp_delta_c")
    if usable(skin) and skin.value >= THRESHOLDS["review_skin_temp_c"]:
        strong.append("nhiệt độ da")
    if len(strong) >= 2:
        found.append(Reason(code="MULTI_DEVIATION", kind="review",
                            text="Nhiều chỉ số cùng lệch mạnh so với nền của bạn (" + ", ".join(strong) + "); có thể do "
                                 "ốm, căng thẳng, rượu bia, thiếu ngủ hoặc đeo thiết bị chưa đúng"))

    found += _sleep_signals(sleep_detail)

    missing = [SPECS[metric].label for metric in CORE if not usable(by.get(metric))]
    if missing:
        found.append(Reason(code="NO_DATA", kind="data", text="Chưa có dữ liệu: " + ", ".join(missing)))
    if quality.stale:
        found.append(Reason(code="STALE_SYNC", kind="data",
                            text="Chưa kết nối Google Health" if not quality.connected
                            else "Lần đồng bộ thành công gần nhất đã hơn 24 giờ"))
    if 0 < quality.baseline_days < THRESHOLDS["medium_confidence_days"]:
        found.append(Reason(code="SHORT_BASELINE", kind="data",
                            text=f"Đường nền mới có {quality.baseline_days} ngày dữ liệu"))
    return found


def _state(readings: list[MetricReading], reasons: list[Reason]) -> str:
    by = {reading.metric: reading for reading in readings}
    assessed = [metric for metric in NIGHT
                if by.get(metric) is not None and by[metric].value is not None and by[metric].baseline_n >= MIN_BASELINE_DAYS]
    # Tín hiệu cần xem lại đi trước cả "chưa đủ dữ liệu": SpO2 thấp không cần đường nền để đáng được nêu.
    if any(reason.kind == "review" for reason in reasons):
        return "needs_review"
    if not assessed:
        return "insufficient_data"
    codes = {reason.code for reason in reasons}
    strain = [reason for reason in reasons if reason.kind == "strain"]
    if len(strain) >= 2 and codes & PHYSIOLOGICAL:
        return "recover"
    if strain:
        return "ease_off"
    if any(reason.kind == "positive" for reason in reasons):
        return "ready"
    return "steady"


def _confidence(state: str, readings: list[MetricReading], quality: DataQuality, day: date) -> str:
    if state == "insufficient_data" or quality.stale:
        return "low"
    core = [reading for reading in readings if reading.metric in CORE and reading.value is not None
            and reading.baseline_n >= MIN_BASELINE_DAYS]
    smallest = min((reading.baseline_n for reading in core), default=0)
    current = all(reading.measured_on == day for reading in core)
    if len(core) == len(CORE) and smallest >= THRESHOLDS["high_confidence_days"] and current:
        return "high"
    if len(core) >= 2 and smallest >= THRESHOLDS["medium_confidence_days"]:
        return "medium"
    return "low"


def _recommendations(state: str, codes: set[str], sleep_missing: bool = False) -> list[Recommendation]:
    primary = {"ready": "train_as_planned", "steady": "train_listen", "ease_off": "reduce_intensity",
               "recover": "prioritize_recovery", "needs_review": "check_with_professional",
               "insufficient_data": "sync_device"}[state]
    keys = [primary]
    if "SLEEP_SHORT" in codes:
        keys.append("sleep_earlier")
    if "LOAD_HIGH" in codes:
        keys.append("hold_load")
    if "SLEEP_DEBT" in codes:
        keys.append("repay_sleep")
    if "SLEEP_IRREGULAR" in codes:
        keys.append("regular_schedule")
    if sleep_missing:
        keys.append("log_sleep")
    if "STALE_SYNC" in codes and "sync_device" not in keys:
        keys.append("sync_device")
    return [Recommendation(code=key, text=RECOMMENDATIONS[key]) for key in keys]


def score(state: str, readings: list[MetricReading], reasons: list[Reason]) -> int | None:
    """Điểm sẵn sàng 0–100, hoặc None khi trạng thái không phải một mức sẵn sàng (cần xem lại, thiếu dữ liệu)."""
    band = SCORE["bands"].get(state)
    if band is None:
        return None
    clip = SCORE["z_clip"]
    sign = {"hrv_ms": 1, "resting_hr_bpm": -1, "sleep_minutes": 1}
    total = weight = 0.0
    for reading in readings:
        if reading.metric not in sign or reading.value is None or reading.z is None \
                or reading.baseline_n < MIN_BASELINE_DAYS:
            continue
        z = max(-clip, min(clip, sign[reading.metric] * reading.z))
        if reading.metric == "sleep_minutes":
            z = min(z, SCORE["sleep_z_max"])
        w = SCORE["weights"][reading.metric]
        total += w * z
        weight += w
    raw = SCORE["base"] + SCORE["points_per_sd"] * (total / weight if weight else 0.0)
    raw -= SCORE["other_strain_penalty"] * sum(1 for reason in reasons
                                                if reason.kind == "strain" and reason.code not in PHYSIOLOGICAL)
    low, high = band
    return int(round(max(low, min(high, raw))))


def decide(*, day: date, zone: str, readings: list[MetricReading], trends: list[Trend], load: LoadSummary | None,
           quality: DataQuality, age: int | None, sleep: SleepDetail | None = None) -> DailyAssessmentRead:
    reasons = signals(readings, trends, load, quality, age, sleep)
    state = _state(readings, reasons)
    order = {"review": 0, "strain": 1, "positive": 2, "info": 3, "data": 4}
    reasons.sort(key=lambda reason: order[reason.kind])
    # Chưa đủ dữ liệu thì câu tóm tắt nói thiếu gì trước, không mở đầu bằng một tín hiệu lẻ trông như "ổn".
    wanted = (lambda reason: reason.kind == "data") if state == "insufficient_data" else (lambda reason: reason.kind != "data")
    headline = [reason.text for reason in reasons if wanted(reason)][:2] or [reason.text for reason in reasons][:1]
    summary = LABELS[state] + (": " + "; ".join(headline) if headline else "")
    return DailyAssessmentRead(
        date=day, timezone=zone, algorithm_version=ALGORITHM_VERSION, state=state, label=LABELS[state],
        score=score(state, readings, reasons),
        confidence=_confidence(state, readings, quality, day), summary=summary, reasons=reasons,
        recommendations=_recommendations(state, {reason.code for reason in reasons},
                                         sleep_missing=sleep is not None and sleep.last_night is None),
        metrics=readings, trends=trends, sleep=sleep, load=load, data_quality=quality, method=METHOD,
        disclaimer=DISCLAIMER)


# --------------------------------------------------------------------------------------------------
# Dựng đánh giá sức khoẻ hằng ngày lúc đọc: đọc health_points và nhật ký tập rồi gọi các hàm thuần.
#
# Không có bảng cache: một lần đánh giá đọc 36 ngày dữ liệu theo ngày (vài chục dòng) và luôn khớp
# dữ liệu, consent và phiên bản thuật toán hiện tại. Consent của bên đọc được kiểm ở router.
# --------------------------------------------------------------------------------------------------

# Nền 28 ngày trước ngày đo + 7 ngày xu hướng + 1 ngày lùi khi chỉ số hôm nay chưa có.
WINDOW_DAYS = BASELINE_DAYS + TREND_DAYS + 1


def build(*, day: date, zone: str, now: datetime, daily: list[Any], availability: dict[str, Any], status: Any,
          loads: dict, missing_rpe: int, age: int | None, sleep: list[Any] | None = None) -> DailyAssessmentRead:
    """Phần thuần của một lần đánh giá (test dùng SimpleNamespace thay cho dòng ORM).

    sleep: các phiên ngủ (SleepSessionRead) của 7 ngày thức dậy gần nhất; None khi bên gọi không đọc chúng.
    """
    by_day = {row.local_date: row for row in daily}
    metric_readings = readings(day, by_day, availability)
    detail = None
    if sleep is not None:
        need = round(recommended_sleep_hours(age)[0] * 60)
        detail = sleep_detail(day, sleep, zone, need)
    return decide(day=day, zone=zone, readings=metric_readings, trends=trends(day, by_day),
                            load=load_summary(day, loads, missing_rpe),
                            quality=quality(metric_readings, status, now), age=age, sleep=detail)


async def assess(session, user, *, day: date | None = None, zone: str | None = None,
                 now: datetime | None = None) -> DailyAssessmentRead:
    zone = await ports.user_timezone(session, user.id, zone)
    now = now or datetime.now(timezone.utc)
    day = day or now.astimezone(ZoneInfo(zone)).date()
    start = day - timedelta(days=WINDOW_DAYS)
    daily = await views.daily(session, user.id, start, day, zone)
    loads, missing = await training_analytics.daily_loads(session, user.id, day - timedelta(days=35), day, zone)
    status = await ports.provider_status(session, user.id)
    age = user.age if getattr(user, "age", None) is not None else (
        (status.provider_profile or {}).get("age") if status is not None else None)
    sleep = await views.sleep(session, user.id, day - timedelta(days=TREND_DAYS - 1), day)
    return build(day=day, zone=zone, now=now, daily=daily, availability=await ports.availability(session, user.id),
                 status=status, loads=loads, missing_rpe=missing, age=age, sleep=sleep)
