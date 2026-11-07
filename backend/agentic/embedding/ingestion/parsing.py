"""Phân tích cục bộ, có giới hạn; không tải URL nào do tài liệu cung cấp."""

from html.parser import HTMLParser
from pathlib import Path


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked += 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and not self.blocked:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "br", "li"} and not self.blocked:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and not self.blocked:
            self.parts.append("\n\n")
        if tag in {"script", "style", "iframe", "object"}:
            self.blocked = max(0, self.blocked - 1)

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def extract_text(path, max_bytes, max_chars=10_000_000):
    """Văn bản của một file cục bộ; các trang PDF được ngăn bằng form feed như nguồn văn bản OCR."""
    path = Path(path)
    if not path.is_file():
        raise ValueError("Source file not found")
    if path.stat().st_size > max_bytes:
        raise ValueError("Document exceeds size limit")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted or len(reader.pages) > 1000:
            raise ValueError("Encrypted/oversized PDF")
        content = "\f".join(p.extract_text() or "" for p in reader.pages)
    elif suffix in {".md", ".txt", ".html", ".htm"}:
        content = path.read_text(encoding="utf-8-sig")
        if suffix in {".html", ".htm"}:
            parser = TextHTML()
            parser.feed(content)
            content = "".join(parser.parts)
    else:
        raise ValueError("Unsupported document type")
    if not content.strip() or len(content) > max_chars:
        raise ValueError("Empty or excessive extracted content; OCR is unsupported")
    return content
