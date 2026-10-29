"""Quote and numeral matching shared by the research agent and the finalization API."""
import re
import unicodedata

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
            return False
        position = found + len(part)
    return position > 0


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


def numbers_supported(claim_text, quote):
    available = quoted_numbers([quote])
    return all(number_values(n) & available for n in NUMBER.findall(claim_text))
