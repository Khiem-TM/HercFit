"""Conservative normalization of paginated OCR text, without rewriting facts."""
from collections import Counter
from dataclasses import dataclass, field
import re
import unicodedata


@dataclass
class CleanPage:
    page: int
    content: str
    warnings: list[str] = field(default_factory=list)


def normalized_line(line):
    return re.sub(r'\s+', ' ', line.strip())


def join_drop_cap(match):
    letter, tail = match.groups()
    # "I have" / "I come" are complete words, unlike "I n" (In).
    if letter == 'I' and tail not in {'n', 'f', 't', 's'}:
        return 'I ' + tail
    return letter + tail


def clean_pages(raw, first_page=1, last_page=None, chapter_pages=(), exclude_pages=()):
    # Preserve form feeds: they are physical source-page boundaries.
    raw = unicodedata.normalize('NFKC', raw.replace('\r\n', '\n').replace('\r', '\n'))
    raw = raw.replace('\ufeff', '').replace('\u00ad', '').replace('\u200b', '')
    raw = ''.join(c for c in raw if c in '\n\t\f' or not unicodedata.category(c).startswith('C'))
    pages = raw.split('\f')
    if pages and not pages[-1].strip():
        pages.pop()  # trailing form feed is a terminator, not another physical page
    edge_count = Counter()
    interior = set()
    for page in pages:
        lines = [normalized_line(l) for l in page.splitlines() if l.strip()]
        edge_count.update(set(lines[:2] + lines[-2:]))
        interior.update(lines[2:-2])
    # Remove only frequently repeated margin strings absent from page interiors.
    repeated = {s for s, n in edge_count.items() if n >= max(5, len(pages) // 20) and len(s) < 100 and s not in interior}
    stats = Counter(total_pages=len(pages), source_characters=len(raw))
    selected = []
    for number, page in enumerate(pages, 1):
        if number < first_page or number > (last_page or len(pages)) or number in exclude_pages:
            stats['excluded_pages'] += 1
            continue
        lines = page.splitlines()
        nonempty = [i for i, l in enumerate(lines) if l.strip()]
        margins = set(nonempty[:2] + nonempty[-2:])
        kept = []
        for i, line in enumerate(lines):
            stripped = normalized_line(line)
            drop_cap = (re.fullmatch(r'[A-Z]', stripped) and i + 1 < len(lines)
                        and re.match(r'^\s+[a-z]', lines[i + 1]))
            if i in margins and not drop_cap and (stripped in repeated or re.fullmatch(r'\d{1,4}|[ivxlcdm]{1,8}', stripped, re.I)):
                stats['margin_lines_removed'] += 1
                continue
            kept.append(line.rstrip())
        if number in chapter_pages:
            body = next((i for i, line in enumerate(kept) if
                re.match(r'^[A-Z] {2,}[a-z]', line) or
                re.match(r'^(?:I n|J ust)\b', line) or
                (re.fullmatch(r'[A-Z]\s*', line) and i + 1 < len(kept) and re.match(r'^\s+[a-z]', kept[i + 1]))), None)
            if body is not None:
                stats['chapter_decoration_lines_removed'] += body
                kept = kept[body:]
        # Drop-cap OCR: "M    uscle" -> "Muscle", "I   n" -> "In".
        text = '\n'.join(kept)
        text, split_caps = re.subn(r'(?m)^([A-Z])[ \t]*\n[ \t]{2,}([a-z]+\b)', join_drop_cap, text)
        stats['drop_caps_joined'] += split_caps
        text, count = re.subn(r'(?m)^([A-Z]) {2,}([a-z]+\b)', join_drop_cap, text)
        stats['drop_caps_joined'] += count
        if number in chapter_pages:
            text = re.sub(r'(?m)^(I) (n)\b', join_drop_cap, text)
            text = re.sub(r'(?m)^(J) (ust)\b', join_drop_cap, text)
        # Join only alphabetic line-wrap hyphens followed by a lowercase letter.
        text, count = re.subn(r'([A-Za-z]{2,})-\n[ \t]*([a-z]{2,})', r'\1\2', text)
        stats['hyphenated_wraps_joined'] += count
        blocks = re.split(r'\n\s*\n', text)
        cleaned = []
        for block in blocks:
            rows = [l.rstrip() for l in block.splitlines() if l.strip()]
            if not rows:
                continue
            # Preserve rows in lists/tables; flatten wrapped prose paragraphs.
            tabular = sum(bool(re.search(r'\S\s{3,}\S', l)) for l in rows) >= 2
            listed = any(re.match(r'^\s*(?:[•*]|\d+[.)])\s', l) for l in rows)
            if tabular or listed:
                cleaned.append('\n'.join(normalized_line(l) for l in rows))
            else:
                cleaned.append(' '.join(normalized_line(l) for l in rows))
        text = '\n\n'.join(cleaned).strip()
        warnings = []
        if number in chapter_pages:
            warnings.append('chapter_opening_ocr_review')
        alnum = sum(c.isalnum() for c in text)
        if text and alnum / max(1, sum(not c.isspace() for c in text)) < 0.65:
            warnings.append('low_alphanumeric_ratio')
        if '\ufffd' in text:
            warnings.append('replacement_characters')
        if not text:
            stats['empty_pages'] += 1
            continue
        stats['selected_pages'] += 1
        stats['cleaned_characters'] += len(text)
        selected.append(CleanPage(number, text, warnings))
    return selected, dict(stats)
