"""Chuẩn hoá thời gian t của câu hỏi tiếng Việt thành (start, end, grain), tất định.

Câu hỏi nêu mốc bằng lời ("tuần trước", "3 ngày qua", "tháng 9", "12/10") được giải ở đây; router chỉ đề xuất ngày khi
lời không rõ. Kết quả luôn bị kẹp: không vượt quá hôm nay, không xa hơn MAX_DAYS.
"""

import calendar
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from ..service import normalize

MAX_DAYS = 2 * 366
# Khoảng ngắn đọc từng ngày, khoảng vừa đọc theo tuần, khoảng dài theo tháng (bản ghi thô chỉ giữ 90 ngày).
DAY_GRAIN_MAX = 14
WEEK_GRAIN_MAX = 84
# Không nêu thời gian: cửa sổ mặc định theo kiểu câu hỏi.
DEFAULT_DAYS = {"latest": 90, "followup": 2, "top": 30, "trend": 28}


@dataclass(frozen=True)
class TimeFrame:
    start: date
    end: date
    grain: str  # day | week | month
    basis: str  # text | router | default
    phrase: str | None = None

    def as_dict(self):
        data = asdict(self)
        data["start"], data["end"] = self.start.isoformat(), self.end.isoformat()
        return data


def _grain(start, end):
    span = (end - start).days + 1
    return "day" if span <= DAY_GRAIN_MAX else "week" if span <= WEEK_GRAIN_MAX else "month"


def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _past(day, today):
    """Ngày/tháng không kèm năm mà rơi vào tương lai là của năm trước."""
    return day if day <= today else day.replace(year=day.year - 1)


def _parse_dm(day, month, year, today):
    try:
        if year:
            year = int(year)
            return date(year + 2000 if year < 100 else year, int(month), int(day))
        return _past(date(today.year, int(month), int(day)), today)
    except ValueError:
        return None


# Chỉ dấu "/": "3-4 bữa" không phải ngày. Không kèm năm thì phải có chữ "ngày" ("1/2 bát" là nửa bát).
DM = r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"
ISO = r"(\d{4}-\d{2}-\d{2})"
UNIT_DAYS = {"ngay": 1, "tuan": 7, "thang": 30, "nam": 365}


def _from_text(text, today):
    """(start, end, cụm từ) đầu tiên nhận ra trong câu đã bỏ dấu, hoặc None."""
    rules = []

    def rule(pattern):
        def register(fn):
            rules.append((re.compile(pattern), fn))
            return fn

        return register

    @rule(r"tu (?:ngay )?" + ISO + r" (?:den|toi) (?:ngay )?" + ISO)
    def iso_range(m):
        return date.fromisoformat(m[1]), date.fromisoformat(m[2])

    @rule(r"tu (?:ngay )?" + DM + r" (?:den|toi) (?:ngay )?" + DM)
    def dm_range(m):
        return _parse_dm(m[1], m[2], m[3], today), _parse_dm(m[4], m[5], m[6], today)

    @rule(ISO)
    def iso_day(m):
        day = date.fromisoformat(m[1])
        return day, day

    @rule(r"(\d+) (ngay|tuan|thang|nam) (?:qua|gan day|gan nhat|vua qua|nay)")
    def last_n(m):
        days = int(m[1]) * UNIT_DAYS[m[2]]
        return today - timedelta(days=days - 1), today

    @rule(r"(\d+) (ngay|tuan|thang) truoc")
    def n_ago(m):
        if m[2] == "ngay":
            day = today - timedelta(days=int(m[1]))
            return day, day
        if m[2] == "tuan":
            start = today - timedelta(days=today.weekday() + 7 * int(m[1]))
            return start, start + timedelta(days=6)
        month, year = today.month - int(m[1]), today.year
        while month < 1:
            month, year = month + 12, year - 1
        return _month_bounds(year, month)

    @rule(r"thang (\d{1,2}) nam (?:ngoai|truoc)")
    def month_last_year(m):
        month = int(m[1])
        return _month_bounds(today.year - 1, month) if 1 <= month <= 12 else None

    @rule(r"thang (\d{1,2})(?:[/ ](?:nam )?(\d{4}))?")
    def named_month(m):
        month = int(m[1])
        if not 1 <= month <= 12:
            return None
        year = int(m[2]) if m[2] else today.year
        start, end = _month_bounds(year, month)
        if not m[2] and start > today:
            start, end = _month_bounds(year - 1, month)
        return start, end

    @rule(r"(?:ngay )" + DM + r"|\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
    def dm_day(m):
        parts = (m[1], m[2], m[3]) if m[1] else (m[4], m[5], m[6])
        day = _parse_dm(*parts, today)
        return (day, day) if day else None

    @rule(r"hom kia")
    def day_before(_m):
        day = today - timedelta(days=2)
        return day, day

    # "toi qua" không có ở đây: bỏ dấu thì "tôi quá mệt" cũng thành "toi qua" (resolve xét "tối qua" có dấu).
    @rule(r"hom qua|dem qua|sang qua|trua qua|chieu qua|\x00toiqua")
    def yesterday(_m):
        day = today - timedelta(days=1)
        return day, day

    @rule(r"hom nay|sang nay|trua nay|chieu nay|toi nay|bay gio|hien tai")
    def today_rule(_m):
        return today, today

    @rule(r"tuan truoc")
    def last_week(_m):
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)

    @rule(r"tuan nay")
    def this_week(_m):
        return today - timedelta(days=today.weekday()), today

    @rule(r"tuan qua|7 ngay")
    def past_week(_m):
        return today - timedelta(days=6), today

    @rule(r"thang truoc")
    def last_month(_m):
        first = today.replace(day=1) - timedelta(days=1)
        return _month_bounds(first.year, first.month)

    @rule(r"thang nay")
    def this_month(_m):
        return today.replace(day=1), today

    @rule(r"thang qua|30 ngay")
    def past_month(_m):
        return today - timedelta(days=29), today

    @rule(r"nam ngoai|nam truoc")
    def last_year(_m):
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)

    @rule(r"nam nay")
    def this_year(_m):
        return date(today.year, 1, 1), today

    @rule(r"gan day|dao nay|moi day")
    def recently(_m):
        return today - timedelta(days=13), today

    # Ưu tiên cụm cụ thể nhất: khoảng ngày, ngày tường minh, rồi cụm tương đối, theo thứ tự đăng ký.
    for pattern, fn in rules:
        match = pattern.search(text)
        if match:
            found = fn(match)
            if found and all(found):
                return found[0], found[1], match.group(0)
    return None


def _clamp(start, end, today):
    end = min(end, today)
    start = max(min(start, end), today - timedelta(days=MAX_DAYS))
    return start, max(start, end)


def resolve(question, today, router_start=None, router_end=None, focus=None):
    """Khoảng thời gian của câu hỏi: lời của người dùng trước, rồi ngày router đề xuất, rồi mặc định theo focus."""
    raw = unicodedata.normalize("NFC", (question or "").lower())
    text = normalize(raw)
    if "tối qua" in raw:
        text = text.replace("toi qua", "\x00toiqua", 1)
    found = _from_text(text, today)
    if found:
        start, end, phrase = found
        basis = "text"
    else:
        phrase = None
        try:
            start = date.fromisoformat(router_start) if router_start else None
            end = date.fromisoformat(router_end) if router_end else None
        except ValueError:
            start = end = None
        if start or end:
            start, end, basis = start or end, end or start, "router"
        else:
            days = DEFAULT_DAYS.get(focus, 7)
            start, end, basis = today - timedelta(days=days - 1), today, "default"
    if start > end:
        start, end = end, start
    start, end = _clamp(start, end, today)
    return TimeFrame(start, end, _grain(start, end), basis, phrase)
