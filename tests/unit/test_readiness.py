"""Readiness Decision Engine (domains/analytics/services/daily_health/readiness.py).

Mỗi ngưỡng trong THRESHOLDS có một ca vừa chạm ngưỡng (tín hiệu bật) và một ca vừa lệch về phía kia (tín hiệu tắt).
Tuổi 30 nên khuyến nghị ngủ là 7–9 giờ (420–540 phút).
"""
from datetime import date

import pytest

from domains.analytics.schemas.daily_health import (
    DataQuality,
    LoadSummary,
    MetricReading,
    SleepDetail,
    SleepNight,
    SleepWeek,
    Trend,
)
from domains.analytics.services.daily_health import readiness
from domains.analytics.services.daily_health.readiness import THRESHOLDS, _confidence, decide, signals

DAY = date(2026, 11, 10)
QUALITY = DataQuality(connected=True, stale=False, missing=[], baseline_days=28)


def reading(metric, value, *, baseline=None, z=None, delta=None, n=28, measured_on=DAY):
    return MetricReading(metric=metric, label=metric, unit="u", value=value, measured_on=measured_on, state="ok",
                         baseline=baseline, baseline_n=n, delta=delta, z=z)


def codes(readings=(), trends=(), load=None, sleep=None):
    return {reason.code for reason in signals(list(readings), list(trends), load, QUALITY, 30, sleep)}


def week(**fields):
    base = {"nights": 7, "need_minutes": 420}
    return SleepDetail(week=SleepWeek(**{**base, **fields}))


def night(efficiency, manual=False):
    return SleepDetail(last_night=SleepNight(date=DAY, bedtime="23:00", wake_time="06:30", efficiency_pct=efficiency,
                                             manual=manual),
                       week=SleepWeek(nights=7, need_minutes=420))


def test_insufficient_baseline_gives_insufficient_data():
    short = [reading("sleep_minutes", 400, baseline=450, n=3), reading("hrv_ms", 50, baseline=55, z=-0.5, n=3)]
    result = decide(day=DAY, zone="Asia/Ho_Chi_Minh", readings=short, trends=[], load=None, quality=QUALITY, age=30)
    assert result.state == "insufficient_data"
    assert result.score is None


# (ngưỡng, đầu vào khi tín hiệu bật, đầu vào khi tín hiệu tắt, mã tín hiệu)
CASES = [
    ("sleep_short_vs_baseline_min",
     dict(readings=[reading("sleep_minutes", 450 - THRESHOLDS["sleep_short_vs_baseline_min"], baseline=450)]),
     dict(readings=[reading("sleep_minutes", 451 - THRESHOLDS["sleep_short_vs_baseline_min"], baseline=450)]),
     "SLEEP_SHORT"),
    ("sleep_short_no_baseline_min",
     dict(readings=[reading("sleep_minutes", 420 - THRESHOLDS["sleep_short_no_baseline_min"] - 1)]),
     dict(readings=[reading("sleep_minutes", 420 - THRESHOLDS["sleep_short_no_baseline_min"])]),
     "SLEEP_SHORT"),
    ("rhr_elevated_bpm",
     dict(readings=[reading("resting_hr_bpm", 60, baseline=55, delta=THRESHOLDS["rhr_elevated_bpm"])]),
     dict(readings=[reading("resting_hr_bpm", 59.9, baseline=55, delta=THRESHOLDS["rhr_elevated_bpm"] - 0.1)]),
     "RHR_ELEVATED"),
    ("rhr_low_z",
     dict(readings=[reading("resting_hr_bpm", 52, baseline=55, delta=-3, z=THRESHOLDS["rhr_low_z"])]),
     dict(readings=[reading("resting_hr_bpm", 52, baseline=55, delta=-3, z=THRESHOLDS["rhr_low_z"] + 0.01)]),
     "RHR_BELOW"),
    ("hrv_low_z",
     dict(readings=[reading("hrv_ms", 30, baseline=55, z=THRESHOLDS["hrv_low_z"])]),
     dict(readings=[reading("hrv_ms", 31, baseline=55, z=THRESHOLDS["hrv_low_z"] + 0.01)]),
     "HRV_LOW"),
    ("hrv_high_z",
     dict(readings=[reading("hrv_ms", 60, baseline=55, z=THRESHOLDS["hrv_high_z"])]),
     dict(readings=[reading("hrv_ms", 59, baseline=55, z=THRESHOLDS["hrv_high_z"] - 0.01)]),
     "HRV_ABOVE"),
    ("hrv_trend_drop_pct",
     dict(readings=[reading("hrv_ms", 50, baseline=55, z=0)],
          trends=[Trend(metric="hrv_ms", label="HRV", unit="ms", recent=46, baseline=55, direction="down",
                        delta_pct=-THRESHOLDS["hrv_trend_drop_pct"])]),
     dict(readings=[reading("hrv_ms", 50, baseline=55, z=0)],
          trends=[Trend(metric="hrv_ms", label="HRV", unit="ms", recent=47, baseline=55, direction="down",
                        delta_pct=-THRESHOLDS["hrv_trend_drop_pct"] + 0.1)]),
     "HRV_LOW"),
    ("acwr_high",
     dict(load=LoadSummary(acute_7d=151, chronic_weekly=100, acwr=THRESHOLDS["acwr_high"] + 0.01)),
     dict(load=LoadSummary(acute_7d=151, chronic_weekly=100, acwr=THRESHOLDS["acwr_high"])),
     "LOAD_HIGH"),
    ("review_z",
     dict(readings=[reading("resting_hr_bpm", 70, baseline=55, z=THRESHOLDS["review_z"]),
                    reading("hrv_ms", 20, baseline=55, z=-THRESHOLDS["review_z"])]),
     dict(readings=[reading("resting_hr_bpm", 70, baseline=55, z=THRESHOLDS["review_z"] - 0.01),
                    reading("hrv_ms", 20, baseline=55, z=-THRESHOLDS["review_z"])]),
     "MULTI_DEVIATION"),
    ("review_skin_temp_c",
     dict(readings=[reading("skin_temp_delta_c", THRESHOLDS["review_skin_temp_c"]),
                    reading("hrv_ms", 20, baseline=55, z=-THRESHOLDS["review_z"])]),
     dict(readings=[reading("skin_temp_delta_c", THRESHOLDS["review_skin_temp_c"] - 0.01),
                    reading("hrv_ms", 20, baseline=55, z=-THRESHOLDS["review_z"])]),
     "MULTI_DEVIATION"),
    ("review_spo2_pct",
     dict(readings=[reading("spo2_avg_pct", THRESHOLDS["review_spo2_pct"] - 0.1)]),
     dict(readings=[reading("spo2_avg_pct", THRESHOLDS["review_spo2_pct"])]),
     "SPO2_LOW"),
    ("sleep_debt_min",
     dict(sleep=week(debt_minutes=THRESHOLDS["sleep_debt_min"])),
     dict(sleep=week(debt_minutes=THRESHOLDS["sleep_debt_min"] - 1)),
     "SLEEP_DEBT"),
    ("sleep_debt_min_nights",
     dict(sleep=week(debt_minutes=400, nights=THRESHOLDS["sleep_debt_min_nights"])),
     dict(sleep=week(debt_minutes=400, nights=THRESHOLDS["sleep_debt_min_nights"] - 1)),
     "SLEEP_DEBT"),
    ("bedtime_sd_min",
     dict(sleep=week(bedtime_sd_minutes=THRESHOLDS["bedtime_sd_min"])),
     dict(sleep=week(bedtime_sd_minutes=THRESHOLDS["bedtime_sd_min"] - 0.1)),
     "SLEEP_IRREGULAR"),
    ("efficiency_low_pct",
     dict(sleep=night(THRESHOLDS["efficiency_low_pct"] - 0.1)),
     dict(sleep=night(THRESHOLDS["efficiency_low_pct"])),
     "SLEEP_EFFICIENCY_LOW"),
]


@pytest.mark.parametrize(("threshold", "fires", "quiet", "code"), CASES, ids=[case[0] for case in CASES])
def test_threshold_edges(threshold, fires, quiet, code):
    assert code in codes(**fires)
    assert code not in codes(**quiet)


def core(n):
    return [reading("sleep_minutes", 450, baseline=450, z=0, n=n), reading("hrv_ms", 55, baseline=55, z=0, n=n),
            reading("resting_hr_bpm", 55, baseline=55, z=0, delta=0, n=n)]


@pytest.mark.parametrize(("n", "expected"), [
    (THRESHOLDS["high_confidence_days"], "high"),
    (THRESHOLDS["high_confidence_days"] - 1, "medium"),
    (THRESHOLDS["medium_confidence_days"], "medium"),
    (THRESHOLDS["medium_confidence_days"] - 1, "low"),
])
def test_confidence_edges(n, expected):
    assert _confidence("steady", core(n), QUALITY, DAY) == expected


def test_every_threshold_is_covered():
    covered = {case[0] for case in CASES} | {"high_confidence_days", "medium_confidence_days"}
    assert covered == set(readiness.THRESHOLDS)
