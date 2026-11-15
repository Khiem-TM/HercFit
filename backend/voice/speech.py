"""Lớp lời nói của worker giọng nói: câu đệm khi chờ agent, viết lại câu trả lời thành lời nói và kiểm tra bản viết lại.

Câu trả lời dạng chữ (markdown, số liệu, danh sách) không hợp để đọc nguyên văn. Model viết lại thành lời nói tự nhiên;
code kiểm tra bản viết lại không thêm con số và không nói "đã lưu" khi bản gốc không nói vậy, sai thì đọc bản gốc đã làm
sạch. Cuối cùng code đổi số, giờ, ngày và đơn vị sang chữ vì TTS đọc sai ("818,1" thành "dấu một", "15/11/2026" thành
"một nghìn năm trăm..."). Không phụ thuộc LiveKit để test được ở tests/unit/test_voice_speech.py.
"""

import random
import re
import unicodedata

FAILED_REPLY = "Mình chưa xử lý được yêu cầu này, bạn nói lại giúp mình nhé."

# Câu đệm khi agent đang xử lý: câu đầu theo loại lượt, các câu sau (kind "wait") khi phải chờ lâu.
FILLERS = {
    "log": ["Được, để mình ghi lại nhé.", "Ừm, mình ghi ngay đây.", "Ok, để mình xem nào."],
    "ask": [
        "Hmm, để mình nghĩ chút nhé.",
        "Ồ, để mình xem nào.",
        "Ừm, câu này hay đấy, để mình nghĩ nhé.",
        "À, để mình suy nghĩ một chút.",
    ],
    "approve": ["Được, để mình lưu nhé.", "Ok, mình lưu ngay đây."],
    "reject": ["Ừ, mình huỷ nhé.", "Được, mình bỏ thẻ này nhé."],
    "wait": [
        "Bạn đợi mình chút nhé.",
        "Sắp xong rồi, bạn chờ thêm chút nhé.",
        "Mình vẫn đang xử lý, một chút nữa thôi.",
    ],
}

REWRITE_PROMPT = """Bạn là giọng nói của HercFit, trợ lý dinh dưỡng và tập luyện. Chuyển câu trả lời dạng văn bản của trợ lý \
thành lời nói tiếng Việt tự nhiên, ấm áp, như đang trò chuyện trực tiếp với người dùng.

Quy tắc:
- Xưng "mình", gọi người dùng là "bạn".
- Giữ nguyên ý nghĩa: con số chính, tên món ăn, bài tập, việc đã lưu hay chưa lưu, cảnh báo, câu hỏi và yêu cầu xác nhận.
- Ưu tiên ý chính: bỏ số phụ (đạm, tinh bột, chất béo, từng món trong danh sách) và ngày tháng năm, trừ khi đó chính là \
điều câu trả lời muốn nói.
- Viết con số đúng như văn bản, bằng chữ số (818,1 vẫn là 818,1; 17:41 vẫn là 17:41). Được bỏ bớt số phụ, không được đổi \
hay thêm số.
- Không thêm thông tin, lời khuyên hay lời hứa mà văn bản không có. Không nói đã lưu, đã ghi, đã kiểm tra hay đã làm \
việc gì nếu văn bản không nói vậy.
- Bỏ markdown, ký hiệu, biểu tượng cảm xúc, gạch đầu dòng, đường link và nguồn trích dẫn.
- Tối đa 3 câu ngắn. Văn bản dài thì nói ý chính rồi nói chi tiết có trên màn hình.
- Văn bản nhắc tới thẻ, nút hay lựa chọn bên dưới thì mời người dùng xem trên màn hình.
- Chỉ trả về lời nói, không giải thích."""

ICONS = re.compile("[\U0001f000-\U0001faff⌀-⏿☀-➿⬀-⯿️‍⃣]+ *")
NUMBER = re.compile(r"\d+(?:[.,:/]\d+)*")
# Cụm nói một việc ghi đã xong, so trên chữ không dấu.
DONE = ("da luu", "da ghi", "luu roi", "ghi roi", "luu xong", "ghi xong", "da duoc luu", "da duoc ghi",
        "da cap nhat", "da xoa", "da huy", "da them")
NOT_DONE = ("chua luu", "chua ghi", "khong luu", "khong ghi")
LOG = re.compile(
    r"\b(ghi|luu)\b|\b(vua|da|moi)\s+(an|uong|tap|chay|choi|boi|dap|ngu)\b"
    r"|\b(an|uong)\s+(\d|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi|nua)\b"
)
QUESTION = re.compile(r"\b(bao nhieu|the nao|tai sao|vi sao|nen|co nen|lam sao)\b")


def plain(text: str) -> str:
    """Chữ thường không dấu, chỉ để so khớp."""
    value = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


def filler_kind(text: str) -> str:
    """'log' khi người dùng kể việc vừa làm hoặc nhờ ghi; còn lại 'ask' (câu đệm không giả định gì)."""
    words = plain(text)
    if "?" in text or QUESTION.search(words):
        return "ask"
    return "log" if LOG.search(words) else "ask"


def pick(kind: str, last: str | None = None, rng: random.Random | None = None) -> str:
    """Một câu đệm của loại `kind`, khác câu vừa nói."""
    options = [phrase for phrase in FILLERS.get(kind) or FILLERS["ask"] if phrase != last]
    return (rng or random).choice(options)


def clean(text: str) -> str:
    """Bỏ markdown, icon, link và gạch đầu dòng; mỗi dòng thành một câu."""
    text = ICONS.sub("", text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"(?m)^\s*(?:[-•]|\d+[.)])\s+", "", text)
    text = text.replace("→", ":").replace("·", ",")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = " ".join(line if line[-1] in ".!?:;," else line + "." for line in lines)
    return re.sub(r"\s+", " ", joined).strip()


def fallback(text: str, limit: int = 280) -> str:
    """Bản gốc đã làm sạch, cắt ở cuối câu khi dài; dùng khi bản viết lại lỗi hoặc không giữ đúng ý."""
    sentences = re.split(r"(?<=[.!?])\s+", clean(text))
    spoken = []
    for sentence in sentences:
        if spoken and len(" ".join([*spoken, sentence])) > limit:
            return " ".join(spoken) + " Chi tiết mình để trên màn hình nhé."
        spoken.append(sentence)
    return " ".join(spoken) or FAILED_REPLY


def _numbers(text: str) -> set[str]:
    found = set()
    for token in NUMBER.findall(text):
        parts = re.split(r"[.,:/]", token)
        found.update(part.lstrip("0") or "0" for part in parts)
        found.add("".join(parts).lstrip("0") or "0")
    return found


def _claims(text: str, phrases: tuple[str, ...]) -> bool:
    words = plain(text)
    return any(phrase in words for phrase in phrases)


def faithful(source: str, spoken: str) -> bool:
    """Bản viết lại không có con số nào ngoài bản gốc và không đảo chiều việc đã lưu / chưa lưu."""
    if not spoken.strip() or not _numbers(spoken) <= _numbers(source):
        return False
    if _claims(spoken, DONE) and not _claims(source, DONE):
        return False
    return not (_claims(source, DONE) and _claims(spoken, NOT_DONE) and not _claims(source, NOT_DONE))


DIGITS = "không một hai ba bốn năm sáu bảy tám chín".split()
SCALES = ["", "nghìn", "triệu", "tỷ"]


def _hundreds(n: int, full: bool) -> list[str]:
    hundred, ten, unit = n // 100, n // 10 % 10, n % 10
    words = [DIGITS[hundred], "trăm"] if hundred or full else []
    if ten == 0:
        if unit:
            words += (["linh"] if words else []) + [DIGITS[unit]]
    elif ten == 1:
        words += ["mười"] + (["lăm" if unit == 5 else DIGITS[unit]] if unit else [])
    else:
        words += [DIGITS[ten], "mươi"]
        if unit:
            words.append({1: "mốt", 4: "tư", 5: "lăm"}.get(unit, DIGITS[unit]))
    return words


def number_words(n: int) -> str:
    """Số nguyên đọc bằng tiếng Việt: 21 → hai mươi mốt, 105 → một trăm linh năm, 2026 → hai nghìn không trăm hai mươi sáu."""
    if n == 0:
        return "không"
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    if len(groups) > len(SCALES):
        return " ".join(DIGITS[int(d)] for d in "".join(str(g) for g in reversed(groups)))
    words = []
    for index in range(len(groups) - 1, -1, -1):
        if groups[index]:
            words += _hundreds(groups[index], full=index < len(groups) - 1)
            words += [SCALES[index]] if SCALES[index] else []
    return " ".join(words)


def _decimal_words(token: str) -> str:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token):  # 1.361 là một nghìn ba trăm sáu mươi mốt
        return number_words(int(token.replace(".", "")))
    whole, _, fraction = token.replace(".", ",").partition(",")
    words = number_words(int(whole))
    if fraction:
        part = (" ".join(DIGITS[int(d)] for d in fraction) if fraction.startswith("0") or len(fraction) > 3
                else number_words(int(fraction)))
        words += " phẩy " + part
    return words


UNITS = {"kcal": "ki lô calo", "kg": "ki lô gam", "km": "ki lô mét", "ml": "mi li lít", "g": "gam", "bpm": "nhịp mỗi phút"}


def _day(match: re.Match, text: str) -> str:
    day, month, year = (int(part) if part else None for part in match.groups())
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return match.group(0)
    lead = "" if text[max(0, match.start() - 5):match.start()].lower().endswith("ngày ") else "ngày "
    words = f"{lead}{number_words(day)} tháng {number_words(month)}"
    return words + (f" năm {number_words(year)}" if year else "")


def for_speech(text: str) -> str:
    """Đổi ngày, giờ, phần trăm, đơn vị và số sang chữ để TTS đọc đúng tiếng Việt."""
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", lambda m: _day(m, text), text)
    text = re.sub(
        r"\b([01]?\d|2[0-4]):([0-5]\d)\b",
        lambda m: f"{number_words(int(m[1]))} giờ" + (f" {number_words(int(m[2]))}" if int(m[2]) else ""),
        text,
    )
    text = re.sub(r"(\d+(?:[.,]\d+)*)\s*%", lambda m: f"{_decimal_words(m[1])} phần trăm", text)
    units = "|".join(sorted(UNITS, key=len, reverse=True))
    text = re.sub(rf"(\d+(?:[.,]\d+)*)\s*({units})\b", lambda m: f"{_decimal_words(m[1])} {UNITS[m[2]]}", text)
    text = re.sub(r"\bkcal\b", UNITS["kcal"], text)
    text = re.sub(r"\d+(?:[.,]\d+)*", lambda m: _decimal_words(m[0]), text)
    return re.sub(r"\s+", " ", text).strip()


def spoken_version(source: str, rewritten: str) -> tuple[str, bool]:
    """(câu sẽ đọc, có dùng bản viết lại hay không)."""
    rewritten = ICONS.sub("", rewritten or "").strip()
    used = faithful(source, rewritten)
    return for_speech(rewritten if used else fallback(source)), used
