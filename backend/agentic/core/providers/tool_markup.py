"""Filter model-emitted tool markup from user-visible text; never execute it."""

import re

# DeepSeek có thể sinh lời gọi tool dưới dạng văn bản DSML thô khi endpoint bỏ qua bước phân tích.
_BAR = r"[｜|]"
_DSML_BLOCK = re.compile(
    rf"<{_BAR}DSML{_BAR}(?:tool|function)_calls>.*?(?:</{_BAR}DSML{_BAR}(?:tool|function)_calls>|$)",
    re.S,
)
def strip_tool_markup(text: str) -> str:
    """Câu trả lời cho người dùng không bao giờ hiển thị markup lời gọi tool DSML mà model đã in vào."""
    return _DSML_BLOCK.sub("", text).strip() if "DSML" in text else text


_MARKERS = ("<｜DSML｜", "<|DSML|")


class ToolMarkupFilter:
    """Stream token câu trả lời nhưng giữ lại phần văn bản có thể mở markup DSML, và bỏ
    markup cùng mọi thứ phía sau; câu trả lời cuối (đã lọc) thay cho bản xem trước."""

    def __init__(self) -> None:
        self.pending, self.blocked = "", False

    def feed(self, text: str) -> str:
        if self.blocked:
            return ""
        self.pending += text
        found = [i for i in (self.pending.find(m) for m in _MARKERS) if i >= 0]
        if found:
            self.blocked = True
            out, self.pending = self.pending[: min(found)], ""
            return out
        cut = self.pending.rfind("<")
        tail = self.pending[cut:] if cut >= 0 else ""
        if tail and any(marker.startswith(tail) for marker in _MARKERS):
            out, self.pending = self.pending[:cut], tail
            return out
        out, self.pending = self.pending, ""
        return out


