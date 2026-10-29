"""Deterministic safety policy for nutrition/fitness conversations.

Runs before any model call. "block" verdicts skip tools, research and plan
generation and answer with supportive, safety-first guidance; "caution" verdicts
keep the normal workflow but constrain the final answer. The checks are
intentionally conservative keyword/number rules over accent-free text, so they
are cheap, explainable and testable (see tests/unit/test_safety.py). They do not
diagnose anything and are not a substitute for professional care.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Literal

from models.foods import normalize_food_text

EMERGENCY = "Nếu bạn đang gặp nguy hiểm hoặc có ý định làm hại bản thân, hãy gọi cấp cứu 115 hoặc đến cơ sở y tế gần nhất và báo cho người thân ngay."
MIN_SAFE_KCAL = 1000          # below this we never help plan an unsupervised diet
MAX_SAFE_LOSS_KG_PER_WEEK = 1.0


@dataclass(frozen=True)
class SafetyVerdict:
    category: str
    level: Literal["block", "caution"]
    guidance: str

    def as_state(self) -> dict:
        return asdict(self)


_SELF_HARM = re.compile(r"\b(tu tu|tu sat|muon chet|khong muon song|lam hai ban than|ket lieu|"
                        r"suicide|kill myself|self harm|end my life)\b")
_EATING_DISORDER = re.compile(r"\b(moc hong|moc hong cho non|non ra|tu gay non|an xong (?:roi )?non|thuoc xo de giam|"
                              r"thuoc nhuan trang de giam|nhin an (?:hoan toan|nhieu ngay|\d+ ngay)|nhin doi (?:\d+ ngay|nhieu ngay)|"
                              r"chan an tam than|bieng an tam than|cuong an|so an|so beo den muc|"
                              r"anorexia|bulimia|purge|purging|laxatives? (?:to|for) (?:lose|weight))\b")
_KCAL = re.compile(r"\b(\d{2,4})\s*(?:kcal|calo|calories|cal)\b")
_DAY_WORDS = re.compile(r"\b(moi ngay|1 ngay|mot ngay|ca ngay|hang ngay|ngay|a day|per day|daily)\b")
_MEAL_WORDS = re.compile(r"\b(bua|snack|mon|meal|breakfast|lunch|dinner)\b")
_DIET_INTENT = re.compile(r"\b(an|chi an|an kieng|giam can|giam mo|diet|eat|keto|thuc don|ke hoach)\b")
_RAPID_LOSS = re.compile(r"\bgiam\s+(\d+(?:[.,]\d+)?)\s*(?:kg|ky|can|kilo)\b[^.!?\n]{0,25}?\btrong\s+(\d+)\s*(ngay|tuan|thang)\b")
_AGE = re.compile(r"\b(?:toi|em|minh|con|chau|tui)\s+(?:nam nay\s+)?(\d{1,2})\s*tuoi\b|\b(\d{1,2})\s*tuoi\b")
_LOSS_INTENT = re.compile(r"\b(giam can|giam mo|an kieng|nhin an|cat calo|lose weight|diet)\b")
_MEDICAL = re.compile(r"\b(mang thai|co bau|dang bau|cho con bu|tieu duong|dai thao duong|suy than|benh than|benh tim|"
                      r"tang huyet ap|gout|ozempic|wegovy|semaglutide|mounjaro|tirzepatide|insulin|"
                      r"pregnan|breastfeed|diabet|kidney disease)\b")


def assess(text: str) -> SafetyVerdict | None:
    """Return the most serious verdict for the user's latest message, if any."""
    t = normalize_food_text(text or "")
    if not t:
        return None
    if _SELF_HARM.search(t):
        return SafetyVerdict("self_harm", "block",
                             "Người dùng có thể đang gặp khủng hoảng. Không bàn chuyện ăn kiêng hay tập luyện. "
                             "Trả lời ngắn, ấm áp, không phán xét, khuyến khích nói chuyện với người tin cậy hoặc chuyên gia. " + EMERGENCY)
    if _EATING_DISORDER.search(t):
        return SafetyVerdict("eating_disorder", "block",
                             "Có dấu hiệu hành vi ăn uống gây hại. Không đưa mục tiêu calo, thực đơn giảm cân hay cách nhịn ăn. "
                             "Trả lời đồng cảm, nêu rằng các hành vi này có thể nguy hiểm, khuyến khích gặp bác sĩ hoặc chuyên gia "
                             "dinh dưỡng, tâm lý. " + EMERGENCY)
    for match in _KCAL.finditer(t):
        kcal = int(match.group(1))
        window = t[max(0, match.start() - 40): match.end() + 40]
        # A daily total, not the energy of one meal ("bữa trưa 650 kcal" is normal logging).
        daily = _DAY_WORDS.search(window) and not _MEAL_WORDS.search(window)
        if daily and 0 < kcal < MIN_SAFE_KCAL and _DIET_INTENT.search(t):
            return SafetyVerdict("extreme_deficit", "block",
                                 f"Người dùng muốn ăn khoảng {kcal} kcal/ngày, thấp hơn mức {MIN_SAFE_KCAL} kcal mà HercFit hỗ trợ khi "
                                 "không có giám sát y tế. Không lập kế hoạch ở mức này. Giải thích rủi ro (mất cơ, thiếu vi chất, "
                                 "sỏi mật, rối loạn ăn uống), đề nghị dùng mục tiêu do hệ thống tính (get_nutrition_targets) "
                                 "và gặp chuyên gia nếu cần giảm nhanh.")
    rapid = _RAPID_LOSS.search(t)
    if rapid:
        amount = float(rapid.group(1).replace(",", "."))
        span = int(rapid.group(2)) * {"ngay": 1 / 7, "tuan": 1.0, "thang": 30 / 7}[rapid.group(3)]
        if span > 0 and amount / span > MAX_SAFE_LOSS_KG_PER_WEEK:
            return SafetyVerdict("extreme_deficit", "block",
                                 f"Người dùng muốn giảm {amount:g} kg trong {rapid.group(2)} {rapid.group(3)}, nhanh hơn "
                                 f"{MAX_SAFE_LOSS_KG_PER_WEEK:g} kg/tuần. Không lập kế hoạch theo tốc độ này. Giải thích tốc độ an toàn "
                                 "thường khoảng 0,5–1% cân nặng mỗi tuần, đề xuất mốc thời gian thực tế hơn.")
    age_match = _AGE.search(t)
    if age_match and _LOSS_INTENT.search(t):
        age = int(age_match.group(1) or age_match.group(2))
        if 0 < age < 18:
            return SafetyVerdict("minor_weight_loss", "caution",
                                 "Người dùng có thể dưới 18 tuổi. Không đặt thâm hụt calo hay mục tiêu giảm cân; tập trung vào "
                                 "thói quen lành mạnh, ngủ đủ, vận động và khuyên trao đổi với cha mẹ, bác sĩ hoặc chuyên gia dinh dưỡng.")
    if _MEDICAL.search(t):
        return SafetyVerdict("medical", "caution",
                             "Chủ đề liên quan tình trạng y khoa, thai kỳ hoặc thuốc. Chỉ cung cấp thông tin chung, không chẩn đoán, "
                             "không chỉnh liều thuốc, không đặt thâm hụt calo; khuyên hỏi bác sĩ điều trị trước khi thay đổi chế độ ăn.")
    return None
