"""Soạn thông báo từ đánh giá hằng ngày: hàm thuần, câu chữ do code sinh, không gọi LLM.

Luật (dedup_key quyết định "đã báo chưa", nên gọi lại bao nhiêu lần cũng không lặp):
* briefing (một lần mỗi ngày địa phương, từ giờ briefing): nhãn sẵn sàng, tối đa 2 lý do có số, một dòng
  giấc ngủ và khuyến nghị chính. needs_review chỉ thành briefing TRUNG TÍNH (không nêu chỉ số sinh lý nào):
  HercFit không gửi cảnh báo sinh lý chủ động khi chưa có đánh giá an toàn.
* insufficient_data: chờ dữ liệu đêm qua thêm WAIT_FOR_DATA sau giờ briefing, rồi nhắc một lần mỗi tuần.
* praise (mỗi mã một lần mỗi tuần): xu hướng HRV tăng / nhịp tim nghỉ giảm, khi độ tin cậy từ medium trở lên.
* insight (mỗi mã một lần mỗi tuần): tải tập tăng nhanh, nợ ngủ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from domains.analytics.schemas.daily_health import DailyAssessmentRead
from domains.notifications.schemas.notification import NotificationPreferences

WAIT_FOR_DATA = timedelta(hours=3)
ACTIVE_STATES = {"ready", "steady", "ease_off", "recover"}
TRUSTED = {"high", "medium"}


@dataclass(frozen=True)
class Draft:
    kind: str
    code: str
    priority: int
    dedup_key: str
    title: str
    body: str
    payload: dict[str, Any] = field(default_factory=dict)
    # Hết hạn sau chừng này ngày kể từ ngày của thông báo (briefing của hôm qua không còn ý nghĩa).
    ttl_days: int = 2


def clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def quiet(prefs: NotificationPreferences, local_now: datetime) -> bool:
    start, end, now = clock(prefs.quiet_hours.start), clock(prefs.quiet_hours.end), local_now.time()
    if start == end:
        return False
    return start <= now < end if start < end else (now >= start or now < end)


def briefing_due(prefs: NotificationPreferences, local_now: datetime) -> bool:
    return local_now.time() >= clock(prefs.briefing_time)


def _duration(minutes: Any) -> str:
    minutes = int(minutes)
    return f"{minutes // 60}h{minutes % 60:02d}"


def _sleep_line(assessment: DailyAssessmentRead) -> str | None:
    sleep = assessment.sleep
    if sleep is None or sleep.last_night is None or sleep.last_night.minutes_asleep is None:
        return None
    night = sleep.last_night
    line = f"Đêm qua ngủ {_duration(night.minutes_asleep)} ({night.bedtime}–{night.wake_time}"
    if night.efficiency_pct is not None and not night.manual:
        line += f", hiệu quả {night.efficiency_pct:g}%"
    line += ", ghi tay)" if night.manual else ")"
    if sleep.week.debt_minutes and sleep.week.debt_minutes >= 60:
        line += f"; nợ ngủ {sleep.week.nights} đêm gần nhất {_duration(sleep.week.debt_minutes)}"
    return line + "."


def _payload(assessment: DailyAssessmentRead, *codes: str) -> dict[str, Any]:
    """Ảnh chụp để kiểm toán: đã báo gì, theo phiên bản thuật toán nào (không có chuỗi số đo)."""
    return {"date": assessment.date.isoformat(), "state": assessment.state, "confidence": assessment.confidence,
            "algorithm_version": assessment.algorithm_version, "reasons": list(codes)}


def _briefing(assessment: DailyAssessmentRead) -> Draft:
    key = f"briefing:{assessment.date.isoformat()}"
    if assessment.state == "needs_review":
        return Draft("briefing", "BRIEFING_NEUTRAL", 2, key, "Đánh giá sức khoẻ hôm nay",
                     "Bản đánh giá hôm nay đã sẵn sàng. Mở bảng sức khoẻ để xem chi tiết.",
                     _payload(assessment))
    reasons = [reason for reason in assessment.reasons if reason.kind in ("strain", "positive")][:2]
    lines = [reason.text + "." for reason in reasons]
    if (sleep := _sleep_line(assessment)) is not None:
        lines.append(sleep)
    if assessment.recommendations:
        lines.append(assessment.recommendations[0].text)
    if assessment.confidence == "low":
        lines.append("Độ tin cậy thấp vì dữ liệu còn thiếu.")
    title = f"Sẵn sàng hôm nay: {assessment.label}"
    priority = 1 if assessment.state in ("ease_off", "recover") else 2
    return Draft("briefing", f"BRIEFING_{assessment.state.upper()}", priority, key, title, " ".join(lines),
                 _payload(assessment, *(reason.code for reason in reasons)))


def _data_quality(assessment: DailyAssessmentRead) -> Draft:
    missing = next((reason.text for reason in assessment.reasons if reason.code == "NO_DATA"), "Chưa có dữ liệu đêm qua")
    body = (f"{missing}. Đeo thiết bị khi ngủ và đồng bộ Google Health, hoặc ghi tay giờ ngủ trong bảng sức khoẻ "
            "để HercFit đánh giá được độ sẵn sàng.")
    return Draft("data_quality", "NO_DATA", 3, f"data_quality:{iso_week(assessment.date)}",
                 "Chưa đủ dữ liệu cho bản tóm tắt", body, _payload(assessment, "NO_DATA"), ttl_days=7)


def _praise(assessment: DailyAssessmentRead) -> list[Draft]:
    trends = {trend.metric: trend for trend in assessment.trends}
    found = []
    hrv, rhr = trends.get("hrv_ms"), trends.get("resting_hr_bpm")
    week = iso_week(assessment.date)
    if hrv is not None and hrv.direction == "up" and hrv.delta_pct is not None:
        found.append(Draft("praise", "HRV_TREND_UP", 3, f"praise:HRV_TREND_UP:{week}", "Hồi phục đang tốt lên",
                           f"HRV 7 ngày của bạn ({hrv.recent:g} ms) cao hơn nền {hrv.delta_pct:g}% "
                           f"({hrv.baseline:g} ms). Giữ nhịp ngủ và tập như hiện tại.",
                           _payload(assessment, "HRV_TREND_UP"), ttl_days=7))
    if rhr is not None and rhr.direction == "down" and rhr.delta_pct is not None:
        found.append(Draft("praise", "RHR_TREND_DOWN", 3, f"praise:RHR_TREND_DOWN:{week}", "Nhịp tim nghỉ đang giảm",
                           f"Nhịp tim nghỉ 7 ngày ({rhr.recent:g} bpm) thấp hơn nền ({rhr.baseline:g} bpm). "
                           "Thường là dấu hiệu thể lực và hồi phục tốt.",
                           _payload(assessment, "RHR_TREND_DOWN"), ttl_days=7))
    return found


INSIGHTS = {"LOAD_HIGH": ("Tải tập tăng nhanh", "hold_load"), "SLEEP_DEBT": ("Nợ ngủ tuần này", "repay_sleep")}


def _insights(assessment: DailyAssessmentRead) -> list[Draft]:
    from domains.analytics.services.daily_health.readiness import RECOMMENDATIONS

    week = iso_week(assessment.date)
    return [Draft("insight", reason.code, 2, f"insight:{reason.code}:{week}", INSIGHTS[reason.code][0],
                  f"{reason.text}. {RECOMMENDATIONS[INSIGHTS[reason.code][1]]}", _payload(assessment, reason.code),
                  ttl_days=7)
            for reason in assessment.reasons if reason.code in INSIGHTS]


def compose(assessment: DailyAssessmentRead, prefs: NotificationPreferences, local_now: datetime, *,
            force: bool = False) -> list[Draft]:
    """Các thông báo nên có tại thời điểm local_now (giờ địa phương), theo thứ tự ưu tiên.

    force: người dùng bấm "Tạo tóm tắt hôm nay": không chờ giờ briefing hay chờ dữ liệu.
    """
    categories = set(prefs.categories)
    due = force or briefing_due(prefs, local_now)
    drafts: list[Draft] = []
    state = assessment.state
    if due and "briefing" in categories and state in ACTIVE_STATES | {"needs_review"}:
        drafts.append(_briefing(assessment))
    if state == "insufficient_data" and "data_quality" in categories:
        deadline = datetime.combine(assessment.date, clock(prefs.briefing_time), local_now.tzinfo) + WAIT_FOR_DATA
        if force or local_now >= deadline:
            drafts.append(_data_quality(assessment))
    if state in ACTIVE_STATES:
        if "praise" in categories and assessment.confidence in TRUSTED:
            drafts += _praise(assessment)
        if "insight" in categories:
            drafts += _insights(assessment)
    return sorted(drafts, key=lambda draft: draft.priority)
