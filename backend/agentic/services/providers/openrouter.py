"""OpenRouter Chat Completions adapter for the pinned langchain-openai version."""

from contextvars import ContextVar
from copy import deepcopy

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIError, APIStatusError

from agentic.services.providers.openrouter_policy import response_metadata

_stream_state = ContextVar("openrouter_stream_state", default=None)


class OpenRouterResponseError(ValueError):
    """Provider failed after HTTP headers were sent. Never include its raw body."""

    def __init__(self, message, *, billing=None):
        super().__init__(message)
        self.billing = billing


def check_response(data):
    choices = data.get("choices") or []
    if data.get("error") or any(
        c.get("error") or c.get("finish_reason") == "error" for c in choices
    ):
        raise OpenRouterResponseError("OpenRouter generation failed")


def require_structured_output(value):
    if value is None:
        raise ValueError("Structured output missing")
    return value


class OpenRouterChatOpenAI(ChatOpenAI):
    """Preserve reasoning round trips and billed cost without exposing reasoning as text.

    No FPT payload rewrites, DSML recovery or cumulative-usage conversion. The
    Chat Completions API is explicit so SDK heuristics cannot switch to Responses.
    """

    use_responses_api: bool | None = False

    def _stream(self, *args, **kwargs):
        state = {"metadata": {}, "finished": False}
        token = _stream_state.set(state)
        try:
            yield from super()._stream(*args, **kwargs)
            if not state["finished"]:
                raise OpenRouterResponseError("OpenRouter stream ended before completion")
        except APIError as exc:
            if isinstance(exc, (APIStatusError, APIConnectionError)):
                raise
            raise OpenRouterResponseError("OpenRouter generation failed") from None
        finally:
            _stream_state.reset(token)

    async def _astream(self, *args, **kwargs):
        state = {"metadata": {}, "finished": False}
        token = _stream_state.set(state)
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
            if not state["finished"]:
                raise OpenRouterResponseError("OpenRouter stream ended before completion")
        except APIError as exc:
            if isinstance(exc, (APIStatusError, APIConnectionError)):
                raise
            raise OpenRouterResponseError("OpenRouter generation failed") from None
        finally:
            _stream_state.reset(token)

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # The reviewed hosts do not advertise this SDK parameter. Keep strict
        # provider filtering and enforce the single-call contract on the result.
        if payload.pop("parallel_tool_calls", False):
            raise ValueError("Parallel tool calls are not supported by this adapter")
        messages = self._convert_input(input_).to_messages()
        for message, wire in zip(messages, payload.get("messages", [])):
            if isinstance(message, AIMessage):
                for key in ("reasoning", "reasoning_details"):
                    if key in message.additional_kwargs:
                        wire[key] = deepcopy(message.additional_kwargs[key])
        return payload

    def _create_chat_result(self, response, generation_info=None):
        data = response if isinstance(response, dict) else response.model_dump()
        check_response(data)
        result = super()._create_chat_result(response, generation_info)
        metadata = response_metadata(data)
        for gen, choice in zip(result.generations, data.get("choices") or []):
            gen.message.response_metadata.update(metadata)
            for key in ("reasoning", "reasoning_details"):
                if choice["message"].get(key) is not None:
                    gen.message.additional_kwargs[key] = deepcopy(choice["message"][key])
            if gen.message.invalid_tool_calls:
                raise OpenRouterResponseError(
                    "Invalid tool call arguments",
                    billing={"metadata": metadata, "usage": data.get("usage") or {}},
                )
            if len(gen.message.tool_calls) > 1:
                # parallel_tool_calls=False cannot be sent (no reviewed host accepts it under
                # require_parameters), so apply it here: keep the first call, as the server would.
                # Failing the turn instead broke 7/234 E1 runs (coach, training_log) on 2026-11-16.
                first = gen.message.tool_calls[0]
                gen.message.tool_calls = [first]
                raw = gen.message.additional_kwargs.get("tool_calls")
                if raw:
                    gen.message.additional_kwargs["tool_calls"] = [c for c in raw if c.get("id") == first["id"]][:1]
        return result

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        check_response(chunk)
        state = _stream_state.get()
        if state is not None:
            state["metadata"].update(response_metadata(chunk))
            if any(c.get("finish_reason") for c in chunk.get("choices") or []):
                state["finished"] = True
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if result is None:
            return None
        # Strings would concatenate when LangChain merges chunks. Emit stable
        # identifiers only on the terminal usage chunk; cost is also terminal.
        if chunk.get("usage"):
            result.message.response_metadata.update(
                state["metadata"] if state is not None else response_metadata(chunk)
            )
        choices = chunk.get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}
        for key in ("reasoning", "reasoning_details"):
            if delta.get(key) is not None:
                result.message.additional_kwargs[key] = deepcopy(delta[key])
        return result

    def with_structured_output(self, schema=None, *, method="function_calling", **kwargs):
        kwargs.setdefault("strict", False)
        output = super().with_structured_output(schema, method=method, **kwargs)
        if kwargs.get("include_raw"):
            return output
        output = output | RunnableLambda(require_structured_output)
        if not self.max_retries:
            return output  # one attempt by request: an agent model escalates to the role model instead
        # Reviewed hosts still return empty or invalid tool arguments for 2-4% of forced calls (probe
        # 2026-11-16); one fresh sample recovers them. Timeouts and HTTP errors are not ValueError and
        # keep only the SDK retry policy, so a hung call never doubles the latency tail.
        return output.with_retry(
            retry_if_exception_type=(ValueError,), stop_after_attempt=2, wait_exponential_jitter=False
        )
