"""So khớp trích dẫn và chữ số dùng chung cho agent tra cứu và API finalize."""

import re
import unicodedata
from difflib import SequenceMatcher

_CANON_MAP = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
    }
)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def canon(text):
    """NFC, thống nhất ngoặc kép/gạch ngang/khoảng trắng, không phân biệt hoa thường: văn bản web và
    đầu ra model thường chỉ khác nhau ở dạng Unicode (tiếng Việt NFD so với NFC) hoặc kiểu chữ."""
    return " ".join(
        unicodedata.normalize("NFC", text or "").translate(_CANON_MAP).casefold().split()
    )


def quote_found(quote, content):
    body = canon(content)
    parts = [canon(p).strip(" .,;:\"'") for p in re.split(r"\.\.\.|…", quote)]
    position = 0
    for part in [p for p in parts if p]:
        found = body.find(part, position)
        if found < 0:
            return near_quote_found(quote, content)
        position = found + len(part)
    return position > 0


# Sách scan có lỗi OCR ("ik" thay cho "in") mà model âm thầm sửa khi trích dẫn.
NEAR_MIN_TOKENS = 6
NEAR_RATIO = 0.9


def _tokens(text):
    return re.findall(r"\w+", canon(text))


def _numbers(tokens):
    return [t for t in tokens if t[0].isdigit()]


def near_quote_found(quote, content):
    """Mọi phần của trích dẫn khớp với nguồn theo thứ tự, từng từ một, với tối đa ~10%
    số từ khác nhau, và đúng y các con số theo đúng thứ tự. Trích dẫn ngắn và mọi
    thay đổi ở con số vẫn đòi hỏi khớp chính xác."""
    body = _tokens(content)
    start = 0
    parts = [_tokens(p) for p in re.split(r"\.\.\.|…", quote)]
    for part in [p for p in parts if p]:
        if len(part) < NEAR_MIN_TOKENS:
            return False
        end = _near(part, body, start)
        if end is None:
            return False
        start = end
    return start > 0


def _near(part, body, start):
    numbers = _numbers(part)
    for size in (len(part), len(part) - 1, len(part) + 1):
        for index in range(start, len(body) - size + 1):
            window = body[index : index + size]
            # Neo vào một trong hai từ ở đầu hoặc cuối, và không bao giờ chấp nhận cửa sổ có con số khác.
            if (window[0] != part[0] and window[-1] != part[-1]) or _numbers(window) != numbers:
                continue
            matcher = SequenceMatcher(None, part, window, autojunk=False)
            if matcher.quick_ratio() >= NEAR_RATIO and matcher.ratio() >= NEAR_RATIO:
                return index + size
    return None


def number_values(raw):
    """Các cách đọc một chữ số: '1.000' là 1000 trong tiếng Việt và 1.0 trong tiếng Anh,
    '1,5' là 1.5, '1,000.5' là 1000.5. Trả về mọi cách đọc hợp lý."""
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        other = "." if decimal == "," else ","
        return {float(raw.replace(other, "").replace(decimal, "."))}
    for separator in (",", "."):
        if separator in raw:
            parts = raw.split(separator)
            if len(parts) > 2:
                return {float("".join(parts))}
            head, tail = parts
            values = {float(head + "." + tail)}
            if len(tail) == 3:
                values.add(float(head + tail))
            return values
    return {float(raw)}


def quoted_numbers(quotes):
    return set().union(*(number_values(n) for quote in quotes for n in NUMBER.findall(quote)))


def numbers_supported(claim_text, quote, context=""):
    """Mọi con số trong khẳng định đều có trong trích dẫn, hoặc trong `context` (câu hỏi của chính người dùng,
    mà khẳng định được phép nhắc lại con số, như "5K" đang được hỏi)."""
    available = quoted_numbers([quote, context])
    return all(number_values(n) & available for n in NUMBER.findall(claim_text))
