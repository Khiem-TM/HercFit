"""Exact E5 tokenizer; only tokenizer.json is downloaded, never model weights."""
from pathlib import Path

import httpx

MODEL = 'intfloat/multilingual-e5-large'
REVISION = '3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3'


def fetch_tokenizer(path):
    path = Path(path)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        response = client.get(f'https://huggingface.co/{MODEL}/resolve/{REVISION}/tokenizer.json')
        response.raise_for_status()
    temporary = path.with_suffix('.download')
    temporary.write_bytes(response.content)
    # Fail before promoting an incomplete or unexpected download.
    from tokenizers import Tokenizer
    Tokenizer.from_file(str(temporary))
    temporary.replace(path)
    return path


class E5Tokenizer:
    def __init__(self, path):
        from tokenizers import Tokenizer
        if not Path(path).is_file():
            raise ValueError('Tokenizer missing; run cli fetch-tokenizer first')
        self.tokenizer = Tokenizer.from_file(str(path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()

    def count(self, content, prefix=''):
        """Tokens of the exact embedding input: 'passage: ', an optional context header, the passage."""
        return len(self.tokenizer.encode('passage: ' + prefix + content).ids)

    def split(self, content, max_tokens=480, overlap_tokens=64, prefix=''):
        """(piece, token_count) windows; see spans() for their character offsets."""
        for _, _, piece, count in self.spans(content, max_tokens, overlap_tokens, prefix):
            yield piece, count

    def spans(self, content, max_tokens=480, overlap_tokens=64, prefix=''):
        """(start, end, piece, token_count): content[start:end] == piece, counted with `prefix`."""
        if not 32 <= max_tokens <= 512 or not 0 <= overlap_tokens < max_tokens // 2:
            raise ValueError('Require 32 <= max_tokens <= 512 and overlap < half the budget')
        reserved = self.count('', prefix) - self.count('')
        # Offset boundaries preserve source spelling; decoding subwords can alter whitespace.
        encoding = self.tokenizer.encode(content, add_special_tokens=False)
        offsets = encoding.offsets
        start = 0
        while start < len(offsets):
            end = min(len(offsets), start + max_tokens - 8 - reserved)
            while end > start:
                piece = content[offsets[start][0]:offsets[end - 1][1]].strip()
                if piece and self.count(piece, prefix) <= max_tokens:
                    break
                end -= 1
            if end <= start:
                raise ValueError('Cannot fit a token span into embedding budget')
            # Prefer a paragraph/sentence boundary in the last quarter of the window.
            if end < len(offsets):
                import re
                boundaries = list(re.finditer(r'\n\n|[.!?][\"\u201d\u2019]?\s+', piece))
                late = [m for m in boundaries if m.end() > len(piece) * 0.75]
                if late:
                    cut = offsets[start][0] + late[-1].end()
                    candidate = end
                    while candidate > start and offsets[candidate - 1][1] > cut:
                        candidate -= 1
                    if candidate > start:
                        end = candidate
                        piece = content[offsets[start][0]:offsets[end - 1][1]].strip()
            begin = content.index(piece, offsets[start][0])
            yield begin, begin + len(piece), piece, self.count(piece, prefix)
            if end == len(offsets):
                break
            # Avoid overlapping windows beginning inside a word.
            next_start = max(start + 1, end - overlap_tokens)
            while next_start < end - 1 and offsets[next_start][0] > 0 and content[offsets[next_start][0] - 1].isalnum():
                next_start += 1
            start = next_start
