"""FPT Marketplace OpenAI-compatible chat/tool/stream adapter."""
import json
import re
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

# DeepSeek may emit tool calls as raw DSML text when the endpoint skips parsing.
_BAR = r"[｜|]"
_DSML_BLOCK = re.compile(rf"<{_BAR}DSML{_BAR}(?:tool|function)_calls>.*?(?:</{_BAR}DSML{_BAR}(?:tool|function)_calls>|$)", re.S)
_DSML_INVOKE = re.compile(rf"<{_BAR}DSML{_BAR}invoke\s+name=\"([^\"]+)\"\s*>(.*?)</{_BAR}DSML{_BAR}invoke>", re.S)
_DSML_PARAM = re.compile(rf"<{_BAR}DSML{_BAR}parameter\s+name=\"([^\"]+)\"(?:\s+string=\"(true|false)\")?\s*>(.*?)</{_BAR}DSML{_BAR}parameter>", re.S)


def _dsml_value(raw: str, is_string: str | None) -> Any:
    if is_string == "true":
        return raw.strip()
    try:
        return json.loads(raw)
    except ValueError:
        return raw.strip()


def recover_dsml_tool_calls(message: AIMessage) -> AIMessage:
    """Turn DSML tool-call text in content into structured tool_calls."""
    content = message.content
    if message.tool_calls or not isinstance(content, str) or "DSML" not in content:
        return message
    calls = []
    for block in _DSML_BLOCK.findall(content):
        for name, body in _DSML_INVOKE.findall(block):
            args = {key: _dsml_value(raw, flag or None) for key, flag, raw in _DSML_PARAM.findall(body)}
            calls.append({"name": name, "args": args, "id": f"call_{uuid4().hex}", "type": "tool_call"})
    if not calls:
        return message
    return message.model_copy(update={"content": _DSML_BLOCK.sub("", content).strip(), "tool_calls": calls})


def strip_tool_markup(text: str) -> str:
    """A user-facing answer never shows DSML tool-call markup the model printed into it."""
    return _DSML_BLOCK.sub("", text).strip() if "DSML" in text else text


_MARKERS = ("<｜DSML｜", "<|DSML|")


class ToolMarkupFilter:
    """Streams answer tokens but holds back text that may open DSML markup, and drops the
    markup and everything after it; the final reply (stripped) replaces the preview."""

    def __init__(self) -> None:
        self.pending, self.blocked = "", False

    def feed(self, text: str) -> str:
        if self.blocked:
            return ""
        self.pending += text
        found = [i for i in (self.pending.find(m) for m in _MARKERS) if i >= 0]
        if found:
            self.blocked = True
            out, self.pending = self.pending[:min(found)], ""
            return out
        cut = self.pending.rfind("<")
        tail = self.pending[cut:] if cut >= 0 else ""
        if tail and any(marker.startswith(tail) for marker in _MARKERS):
            out, self.pending = self.pending[:cut], tail
            return out
        out, self.pending = self.pending, ""
        return out


class FPTChatOpenAI(ChatOpenAI):
    """Keep validated Pydantic output via function calling, not JSON-schema mode.

    FPT uses its root endpoint (no automatically appended /v1). API credentials
    are injected as SecretStr by the model factory, never embedded in prompts.
    """

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
            ChatGeneration(message=recover_dsml_tool_calls(gen.message), generation_info=gen.generation_info)
            if isinstance(gen.message, AIMessage) else gen
            for gen in result.generations
        ]
        return result

    def with_structured_output(
        self, schema: Any = None, *, method: str = "function_calling", **kwargs: Any
    ):
        kwargs.setdefault("strict", False)
        return super().with_structured_output(schema, method=method, **kwargs)
