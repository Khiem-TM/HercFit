"""Quote and numeral matching shared by the research agent and the finalization API."""
import re
import unicodedata
from difflib import SequenceMatcher

_CANON_MAP = str.maketrans({'“': '"', '”': '"', '„': '"', '«': '"', '»': '"', '‘': "'", '’': "'", '‚': "'",
                            '–': '-', '—': '-', '−': '-', ' ': ' ', ' ': ' ', ' ': ' '})
NUMBER = re.compile(r'\d+(?:[.,]\d+)*')


def canon(text):
    """NFC, unified quotes/dashes/spaces, case-folded: web text and model output
    often differ only in Unicode form (Vietnamese NFD vs NFC) or typography."""
    return ' '.join(unicodedata.normalize('NFC', text or '').translate(_CANON_MAP).casefold().split())


def quote_found(quote, content):
    body = canon(content)
    parts = [canon(p).strip(' .,;:"\'') for p in re.split(r'\.\.\.|…', quote)]
    position = 0
    for part in [p for p in parts if p]:
        found = body.find(part, position)
        if found < 0:
            return near_quote_found(quote, content)
        position = found + len(part)
    return position > 0


# Scanned books carry OCR slips ("ik" for "in") that a model silently corrects when quoting.
NEAR_MIN_TOKENS = 6
NEAR_RATIO = .9


def _tokens(text):
    return re.findall(r'\w+', canon(text))


def _numbers(tokens):
    return [t for t in tokens if t[0].isdigit()]


def near_quote_found(quote, content):
    """Every part of the quote matches the source in order, word by word, with at most ~10% of its
    words differing, and with exactly the same numbers in the same order. Short quotes and any
    change to a number still require an exact match."""
    body = _tokens(content)
    start = 0
    parts = [_tokens(p) for p in re.split(r'\.\.\.|…', quote)]
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
            window = body[index:index + size]
            # Anchor on either end word, and never accept a window whose numbers differ.
            if (window[0] != part[0] and window[-1] != part[-1]) or _numbers(window) != numbers:
                continue
            matcher = SequenceMatcher(None, part, window, autojunk=False)
            if matcher.quick_ratio() >= NEAR_RATIO and matcher.ratio() >= NEAR_RATIO:
                return index + size
    return None


def number_values(raw):
    """Readings of one numeral: '1.000' is 1000 in Vietnamese and 1.0 in English,
    '1,5' is 1.5, '1,000.5' is 1000.5. Every plausible reading is returned."""
    if ',' in raw and '.' in raw:
        decimal = ',' if raw.rfind(',') > raw.rfind('.') else '.'
        other = '.' if decimal == ',' else ','
        return {float(raw.replace(other, '').replace(decimal, '.'))}
    for separator in (',', '.'):
        if separator in raw:
            parts = raw.split(separator)
            if len(parts) > 2:
                return {float(''.join(parts))}
            head, tail = parts
            values = {float(head + '.' + tail)}
            if len(tail) == 3:
                values.add(float(head + tail))
            return values
    return {float(raw)}


def quoted_numbers(quotes):
    return set().union(*(number_values(n) for quote in quotes for n in NUMBER.findall(quote)))


def numbers_supported(claim_text, quote, context=''):
    """Every number in the claim is in its quote, or in `context` (the user's own question, whose
    numbers a claim may restate, such as the "5K" being asked about)."""
    available = quoted_numbers([quote, context])
    return all(number_values(n) & available for n in NUMBER.findall(claim_text))
