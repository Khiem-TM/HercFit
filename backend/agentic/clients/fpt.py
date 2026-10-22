"""FPT Marketplace OpenAI-compatible chat/tool/stream adapter."""
from typing import Any

from langchain_openai import ChatOpenAI


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

    def with_structured_output(
        self, schema: Any = None, *, method: str = "function_calling", **kwargs: Any
    ):
        kwargs.setdefault("strict", False)
        return super().with_structured_output(schema, method=method, **kwargs)
