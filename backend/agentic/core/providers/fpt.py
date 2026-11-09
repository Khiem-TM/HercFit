"""Adapter chat/tool/stream tương thích OpenAI cho FPT Marketplace."""

import json
import re
from typing import Any, AsyncIterator, Iterator
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

# DeepSeek có thể sinh lời gọi tool dưới dạng văn bản DSML thô khi endpoint bỏ qua bước phân tích.
_BAR = r"[｜|]"
_DSML_BLOCK = re.compile(
    rf"<{_BAR}DSML{_BAR}(?:tool|function)_calls>.*?(?:</{_BAR}DSML{_BAR}(?:tool|function)_calls>|$)",
    re.S,
)
_DSML_INVOKE = re.compile(
    rf"<{_BAR}DSML{_BAR}invoke\s+name=\"([^\"]+)\"\s*>(.*?)</{_BAR}DSML{_BAR}invoke>", re.S
)
_DSML_PARAM = re.compile(
    rf"<{_BAR}DSML{_BAR}parameter\s+name=\"([^\"]+)\"(?:\s+string=\"(true|false)\")?\s*>(.*?)</{_BAR}DSML{_BAR}parameter>",
    re.S,
)


def _dsml_value(raw: str, is_string: str | None) -> Any:
    if is_string == "true":
        return raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw.strip()


def recover_dsml_tool_calls(message: AIMessage) -> AIMessage:
    """Chuyển văn bản lời gọi tool DSML trong content thành tool_calls có cấu trúc."""
    content = message.content
    if message.tool_calls or not isinstance(content, str) or "DSML" not in content:
        return message
    calls = []
    for block in _DSML_BLOCK.findall(content):
        for name, body in _DSML_INVOKE.findall(block):
            args = {
                key: _dsml_value(raw, flag or None) for key, flag, raw in _DSML_PARAM.findall(body)
            }
            calls.append(
                {"name": name, "args": args, "id": f"call_{uuid4().hex}", "type": "tool_call"}
            )
    if not calls:
        return message
    return message.model_copy(
        update={"content": _DSML_BLOCK.sub("", content).strip(), "tool_calls": calls}
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


def _usage_delta(current: dict, previous: dict) -> dict:
    """FPT gửi usage lũy kế mỗi chunk; LangChain cộng các chunk nên cần phần tăng thêm."""
    delta = {}
    for key, value in current.items():
        if isinstance(value, dict):
            delta[key] = _usage_delta(value, previous.setdefault(key, {}))
        else:
            old = previous.get(key, 0)
            delta[key] = max(0, value - old)
            previous[key] = max(old, value)
    return delta


class FPTChatOpenAI(ChatOpenAI):
    """Giữ đầu ra Pydantic đã kiểm tra qua function calling, không dùng chế độ JSON-schema.

    FPT dùng endpoint gốc (không tự nối thêm /v1). Thông tin xác thực API
    được factory của model tiêm vào dưới dạng SecretStr, không bao giờ nhúng vào prompt.
    """

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        previous = {}  # riêng mỗi request, kể cả khi cùng client được dùng song song
        for chunk in super()._stream(*args, **kwargs):
            if isinstance(chunk.message, AIMessageChunk) and chunk.message.usage_metadata:
                chunk.message.usage_metadata = _usage_delta(chunk.message.usage_metadata, previous)
            yield chunk

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        previous = {}
        async for chunk in super()._astream(*args, **kwargs):
            if isinstance(chunk.message, AIMessageChunk) and chunk.message.usage_metadata:
                chunk.message.usage_metadata = _usage_delta(chunk.message.usage_metadata, previous)
            yield chunk

    def _get_request_payload(
        self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = payload.get("messages", [])
        leading_sys: list[str] = []
        normalized: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                if not normalized:
                    leading_sys.append(str(msg.get("content", "")))
                elif normalized[-1].get("role") == "user":
                    normalized[-1] = {
                        **normalized[-1],
                        "content": f"{normalized[-1].get('content', '')}\n\n{msg.get('content', '')}",
                    }
                else:
                    normalized.append({"role": "user", "content": str(msg.get("content", ""))})
            else:
                normalized.append(dict(msg))
        if leading_sys:
            payload["messages"] = [
                {"role": "system", "content": "\n\n".join(leading_sys)},
                *normalized,
            ]
        elif normalized:
            payload["messages"] = normalized
        if isinstance(payload.get("tool_choice"), dict):
            for tool in payload.get("tools", []):
                params = tool.get("function", {}).get("parameters")
                if isinstance(params, dict) and "properties" in params:
                    params["required"] = list(params["properties"].keys())
        return payload

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        result.generations = [
            ChatGeneration(
                message=recover_dsml_tool_calls(gen.message), generation_info=gen.generation_info
            )
            if isinstance(gen.message, AIMessage)
            else gen
            for gen in result.generations
        ]
        return result

    def with_structured_output(
        self, schema: Any = None, *, method: str = "function_calling", **kwargs: Any
    ):
        kwargs.setdefault("strict", False)
        return super().with_structured_output(schema, method=method, **kwargs)
