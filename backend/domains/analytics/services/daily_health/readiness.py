"""Readiness Decision Engine: luật tất định, có phiên bản, giải thích được.

Đây là một heuristic thăm dò để gợi ý cường độ tập, KHÔNG phải công cụ đã được kiểm định lâm sàng và
không chẩn đoán gì. Căn cứ:
* có bằng chứng: điều chỉnh tập theo HRV so với nền cá nhân (Kiviniemi và cs., 2007; Plews và cs., 2013);
  thời lượng ngủ khuyến nghị theo tuổi (National Sleep Foundation, Hirshkowitz và cs., 2015);
* heuristic chọn cho HercFit (cần đánh giá thêm): ngưỡng z, 45 phút ngủ hụt, 5 bpm nhịp tim nghỉ (đã dùng ở
  tổng quan sức khoẻ), ACWR > 1,5 (Gabbett, 2016; khái niệm bị phê bình bởi Impellizzeri và cs., 2020),
  nợ ngủ 5 giờ/7 đêm (hậu quả cộng dồn của ngủ thiếu: Van Dongen và cs., 2003), độ lệch giờ ngủ 60 phút
  (độ đều giấc ngủ: Phillips và cs., 2017), hiệu quả ngủ 85%.
Mọi ngưỡng nằm trong THRESHOLDS để đổi phương pháp là đổi phiên bản, không âm thầm đổi câu trả lời cũ.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from domains.analytics.schemas.daily_health import (
    DailyAssessmentRead,
    DataQuality,
    LoadSummary,
    MetricReading,
    Reason,
    Recommendation,
    SleepDetail,
    Trend,
)
from domains.analytics.services.daily_health.analytics import MIN_BASELINE_DAYS, SPECS
from domains.health_records.schemas.health import HRV_DROP_PCT, RHR_ELEVATION_BPM, recommended_sleep_hours

# v2: thêm phân tích giấc ngủ (nợ ngủ 7 đêm, độ đều giờ ngủ, hiệu quả, ngủ ghi tay).
ALGORITHM_VERSION = "readiness-heuristic-v2"
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
          "luật trạng thái tất định; các ngưỡng là heuristic thăm dò.")
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
        confidence=_confidence(state, readings, quality, day), summary=summary, reasons=reasons,
        recommendations=_recommendations(state, {reason.code for reason in reasons},
                                         sleep_missing=sleep is not None and sleep.last_night is None),
        metrics=readings, trends=trends, sleep=sleep, load=load, data_quality=quality, method=METHOD,
        disclaimer=DISCLAIMER)
