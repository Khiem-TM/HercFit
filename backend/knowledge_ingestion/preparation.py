"""Prepare reproducible book artifacts without calling an API or opening the DB."""
import bisect
import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from knowledge_ingestion.cleaning import clean_pages
from knowledge_ingestion.parsing import extract_text
from knowledge_ingestion.tokenization import E5Tokenizer, MODEL, REVISION


class Chapter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    page: int = Field(ge=1)
    title: str
    # Printed page number from the table of contents; maps physical source pages to citable ones.
    printed_page: int | None = Field(default=None, ge=1)


class DocumentSpec(BaseModel):
    """Processing spec for one document; a book adds chapters and its content page range."""
    model_config = ConfigDict(extra='forbid')
    source_key: str
    title: str
    license: str
    author: str | None = None
    edition: str | None = None
    language: str = 'en'
    sport: str = 'running'
    topic: str = 'running-science-and-training'
    first_page: int = Field(default=1, ge=1)
    last_page: int | None = Field(default=None, ge=1)
    max_tokens: int = Field(default=480, ge=32, le=512)
    overlap_tokens: int = Field(default=64, ge=0)
    chapters: list[Chapter] = Field(default_factory=list)
    sections: list[Chapter] = Field(default_factory=list)
    exclude_pages: list[int] = Field(default_factory=list)
    # Join consecutive pages of one chapter so paragraphs are not cut at page breaks.
    join_pages: bool = True
    # Embed each passage after "<title> — <heading>", the context an isolated passage lacks.
    contextual_header: bool = True


PIPELINE = 'chapter-stream-ocr-e5-v3'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def header(title, heading):
    """Context line embedded before a passage; the stored passage itself is unchanged."""
    return f'{title} — {heading}\n' if heading and heading != title else f'{title}\n'


def embedding_text(title, heading, content, contextual=True):
    return (header(title, heading) if contextual else '') + content


def page_join(previous, following):
    """Separator between consecutive pages: a sentence that runs on stays one paragraph."""
    if re.search(r'[A-Za-z]{2,}-$', previous) and re.match(r'[a-z]', following):
        return None  # word hyphenated across the page break
    if re.search(r'[.!?:;"\u201d)\]]$', previous) or not re.match(r'[a-z(]', following):
        return '\n\n'
    return ' '


def streams(pages, boundaries, join):
    """(chapter, text, [(char_offset, page)]) runs of consecutive pages within one chapter."""
    runs = []
    for page in pages:
        chapter = next((c for c in reversed(boundaries) if c.page <= page.page), None)
        last = runs[-1] if runs else None
        if join and last and last[0] is chapter and last[2][-1][1] == page.page - 1:
            separator = page_join(last[1], page.content)
            # A hyphenated word rejoins at the hyphen; otherwise the next page starts after the separator.
            offset = len(last[1]) - 1 if separator is None else len(last[1]) + len(separator)
            runs[-1] = (chapter, last[1][:offset] + page.content if separator is None else last[1] + separator + page.content,
                        last[2] + [(offset, page.page)])
        else:
            runs.append((chapter, page.content, [(0, page.page)]))
    return runs


def printed_label(chapter, first, last):
    """Printed page(s) of physical pages first..last, when the chapter's printed start is known."""
    if not chapter or chapter.printed_page is None:
        return None
    offset = chapter.page - chapter.printed_page
    start, end = first - offset, last - offset
    return str(start) if start == end else f'{start}–{end}'


def prepare(source, output, spec_path, settings):
    source, output = Path(source).resolve(), Path(output).resolve()
    root = Path(settings.KNOWLEDGE_INGEST_ROOT).resolve()
    if not output.is_relative_to(root):
        raise ValueError('Output must be inside KNOWLEDGE_INGEST_ROOT')
    if source.stat().st_size > settings.KNOWLEDGE_MAX_FILE_BYTES:
        raise ValueError('Source exceeds byte limit')
    raw_bytes = source.read_bytes()
    # PDF/HTML/Markdown go through the same bounded extractor; text sources keep their exact bytes.
    raw = extract_text(source, settings.KNOWLEDGE_MAX_FILE_BYTES, settings.KNOWLEDGE_MAX_EXTRACTED_CHARS)
    spec = DocumentSpec.model_validate_json(Path(spec_path).read_text())
    last_page = spec.last_page or len(raw.split('\f'))
    if last_page > len(raw.split('\f')) or spec.first_page > last_page:
        raise ValueError('Invalid source page range')
    chapter_pages = [c.page for c in spec.chapters]
    if chapter_pages != sorted(set(chapter_pages)):
        raise ValueError('Chapters must have unique, increasing source pages')
    boundaries = sorted(spec.chapters + spec.sections, key=lambda c: c.page)
    labelled = [c for c in boundaries if c.printed_page is not None]
    if any(b.printed_page < a.printed_page for a, b in zip(labelled, labelled[1:])):
        raise ValueError('Printed pages must increase with source pages')
    tokenizer = E5Tokenizer(settings.KNOWLEDGE_TOKENIZER_PATH)
    pages, stats = clean_pages(raw, spec.first_page, last_page,
                               [c.page for c in boundaries], spec.exclude_pages)
    rows = []
    duplicate_count = 0
    # Deduplicate only identical chunks within the same run, never across contexts.
    seen = set()
    runs = streams(pages, boundaries, spec.join_pages)
    for chapter, text, starts in runs:
        heading = chapter.title if chapter else spec.title
        prefix = header(spec.title, heading) if spec.contextual_header else ''
        positions = [offset for offset, _ in starts]
        page_at = lambda char: starts[bisect.bisect_right(positions, char) - 1][1]
        for begin, end, content, tokens in tokenizer.spans(text, spec.max_tokens, spec.overlap_tokens, prefix):
            digest = sha256(content.encode())
            if (starts[0][1], digest) in seen:
                duplicate_count += 1
                continue
            seen.add((starts[0][1], digest))
            first, last = page_at(begin), page_at(end - 1)
            rows.append({'position': len(rows), 'page': first, 'page_end': last,
                         'page_label': printed_label(chapter, first, last), 'heading': heading,
                         'content': content, 'token_count': tokens, 'content_sha256': digest})
    if not rows:
        raise ValueError('No chunks produced')
    output.mkdir(parents=True, exist_ok=True)
    # One form feed per run of joined pages; every chunk is a substring of exactly one run.
    clean_bytes = '\f'.join(text for _, text, _ in runs).encode()
    chunks_bytes = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode()
    processing = {
        'pipeline': PIPELINE, 'source_filename': source.name,
        'source_sha256': sha256(raw_bytes), 'spec_sha256': sha256(Path(spec_path).read_bytes()),
        'tokenizer': MODEL, 'tokenizer_revision': REVISION,
        'tokenizer_sha256': sha256(Path(settings.KNOWLEDGE_TOKENIZER_PATH).read_bytes()),
        'max_tokens_including_passage_prefix': spec.max_tokens, 'overlap_tokens': spec.overlap_tokens,
        'page_numbering': '1-based physical source pages; page_label holds printed pages when known',
        'join_pages': spec.join_pages, 'contextual_header': spec.contextual_header,
        'first_page': spec.first_page, 'last_page': last_page, 'exclude_pages': spec.exclude_pages,
        'chunk_count': len(rows),
    }
    manifest = {
        'source_key': spec.source_key, 'title': spec.title, 'license': spec.license,
        'author': spec.author, 'edition': spec.edition,
        'filename': str((output / 'cleaned.txt').relative_to(root)),
        'chunks_filename': str((output / 'chunks.jsonl').relative_to(root)),
        'content_sha256': sha256(clean_bytes), 'chunks_sha256': sha256(chunks_bytes),
        'sport': spec.sport, 'topic': spec.topic, 'language': spec.language,
        'document_type': 'book', 'processing': processing,
    }
    stats.update({
        'source_bytes': len(raw_bytes), 'source_sha256': processing['source_sha256'],
        'chunks': len(rows), 'duplicate_chunks_removed': duplicate_count,
        'max_chunk_tokens': max(r['token_count'] for r in rows),
        'total_embedding_input_tokens': sum(r['token_count'] for r in rows),
        'estimated_batches': (len(rows) + settings.KNOWLEDGE_EMBEDDING_BATCH_SIZE - 1) // settings.KNOWLEDGE_EMBEDDING_BATCH_SIZE,
        'model': settings.EMBEDDING_MODEL, 'dimension': settings.EMBEDDING_DIMENSION,
        'warnings': [{'page': p.page, 'reasons': p.warnings} for p in pages if p.warnings],
        'profile_id': settings.profile_id,
    })
    # Deterministic artifacts; a checksum mismatch makes partial writes fail closed at enqueue.
    (output / 'cleaned.txt').write_bytes(clean_bytes)
    (output / 'chunks.jsonl').write_bytes(chunks_bytes)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (output / 'report.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2) + '\n')
    return stats


def load_prepared(settings, manifest):
    """Validate the exact artifacts that will be inserted, before opening a write transaction."""
    root = Path(settings.KNOWLEDGE_INGEST_ROOT).resolve()
    def read(name):
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Artifact outside ingestion root')
        if path.stat().st_size > settings.KNOWLEDGE_MAX_FILE_BYTES:
            raise ValueError('Artifact exceeds byte limit')
        return path.read_bytes()
    content_bytes, chunks_bytes = read(manifest.filename), read(manifest.chunks_filename)
    if sha256(content_bytes) != manifest.content_sha256 or sha256(chunks_bytes) != manifest.chunks_sha256:
        raise ValueError('Prepared artifact checksum mismatch; rerun prepare')
    tokenizer = E5Tokenizer(settings.KNOWLEDGE_TOKENIZER_PATH)
    if sha256(Path(settings.KNOWLEDGE_TOKENIZER_PATH).read_bytes()) != manifest.processing.get('tokenizer_sha256'):
        raise ValueError('Prepared tokenizer checksum mismatch')
    rows = [json.loads(line) for line in chunks_bytes.decode().splitlines() if line.strip()]
    if len(rows) != manifest.processing.get('chunk_count') or not rows:
        raise ValueError('Prepared chunk count mismatch')
    budget = manifest.processing.get('max_tokens_including_passage_prefix', 480)
    if type(budget) is not int or not 32 <= budget <= 512:
        raise ValueError('Invalid token budget')
    content = content_bytes.decode()
    contextual = manifest.processing.get('contextual_header', False)
    for position, row in enumerate(rows):
        if row.get('position') != position or type(row.get('page')) is not int or row['page'] < 1:
            raise ValueError('Invalid chunk position/page')
        chunk = row.get('content', '')
        if not isinstance(chunk, str) or not chunk.strip() or chunk not in content:
            raise ValueError('Chunk is not present in prepared content')
        prefix = header(manifest.title, row.get('heading')) if contextual else ''
        if sha256(chunk.encode()) != row.get('content_sha256') or tokenizer.count(chunk, prefix) != row.get('token_count') or row['token_count'] > budget:
            raise ValueError('Invalid chunk checksum/token count')
    return content, [{k: row.get(k) for k in ('content', 'heading', 'page', 'page_end', 'page_label')} for row in rows]
