"""Model provider definitions, LLM factories (OpenAI, Anthropic, Gemini, local Ollama, Fake), embeddings, and tracing."""

from dataclasses import dataclass, field
from enum import StrEnum, auto
from functools import cache
import inspect
from typing import Any, Callable

from pydantic import BaseModel, SecretStr

from config.settings import agent_settings
from core.exceptions import ConfigurationError, LLMProviderError

try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.messages import (
        AIMessage,
        AnyMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
    )
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import tool as lc_tool
    from langchain_core.tracers.langchain import LangChainTracer
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False

    class BaseMessage(BaseModel):  # type: ignore[no-redef]
        content: Any
        type: str = "base"
        name: str | None = None
        additional_kwargs: dict[str, Any] = {}

    class HumanMessage(BaseMessage):  # type: ignore[no-redef]
        type: str = "human"

    class AIMessage(BaseMessage):  # type: ignore[no-redef]
        type: str = "ai"

    class SystemMessage(BaseMessage):  # type: ignore[no-redef]
        type: str = "system"

    AnyMessage = BaseMessage | HumanMessage | AIMessage | SystemMessage  # type: ignore[misc]
    RunnableConfig = dict[str, Any]  # type: ignore[misc]
    BaseChatModel = object  # type: ignore[misc,assignment]
    ChatOpenAI = None  # type: ignore[assignment]
    OpenAIEmbeddings = Any  # type: ignore[misc,assignment]
    LangChainTracer = Any  # type: ignore[misc,assignment]

    class FakeListChatModel:  # type: ignore[no-redef]
        def __init__(self, responses: list[str] | None = None) -> None:
            self.responses = responses or ["Fake response"]
            self._idx = 0

        async def ainvoke(self, input_msgs: Any, config: Any = None, **kwargs: Any) -> AIMessage:
            reply = self.responses[self._idx % len(self.responses)]
            self._idx += 1
            return AIMessage(content=reply)

        def invoke(self, input_msgs: Any, config: Any = None, **kwargs: Any) -> AIMessage:
            reply = self.responses[self._idx % len(self.responses)]
            self._idx += 1
            return AIMessage(content=reply)

    @dataclass
    class _FallbackStructuredTool:
        name: str
        func: Callable[..., Any]
        description: str = ""
        args_schema: type[BaseModel] | None = None
        metadata: dict[str, Any] = field(default_factory=dict)

        def invoke(self, input_data: dict[str, Any] | Any = None, **kwargs: Any) -> Any:
            call_kwargs = dict(input_data) if isinstance(input_data, dict) else kwargs
            return self.func(**call_kwargs)

        async def ainvoke(self, input_data: dict[str, Any] | Any = None, **kwargs: Any) -> Any:
            call_kwargs = dict(input_data) if isinstance(input_data, dict) else kwargs
            if inspect.iscoroutinefunction(self.func):
                return await self.func(**call_kwargs)
            return self.func(**call_kwargs)

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self.func(*args, **kwargs)

    def lc_tool(  # type: ignore[misc]
        name_or_callable: str | Callable[..., Any] | None = None,
        *,
        args_schema: type[BaseModel] | None = None,
        description: str | None = None,
    ) -> Any:
        if callable(name_or_callable):
            fn = name_or_callable
            return _FallbackStructuredTool(
                name=fn.__name__,
                func=fn,
                description=description or (fn.__doc__ or "").strip(),
                args_schema=args_schema,
            )

        def _decorator(fn: Callable[..., Any]) -> _FallbackStructuredTool:
            tool_name = name_or_callable if isinstance(name_or_callable, str) else fn.__name__
            return _FallbackStructuredTool(
                name=tool_name,
                func=fn,
                description=description or (fn.__doc__ or "").strip(),
                args_schema=args_schema,
            )

        return _decorator


tool = lc_tool


class Provider(StrEnum):
    OPENAI = auto()
    OPENAI_COMPATIBLE = auto()
    AZURE_OPENAI = auto()
    DEEPSEEK = auto()
    ANTHROPIC = auto()
    GOOGLE = auto()
    VERTEXAI = auto()
    GROQ = auto()
    AWS = auto()
    OLLAMA = auto()
    OPENROUTER = auto()
    FAKE = auto()


class OpenAIModelName(StrEnum):
    GPT_5_NANO = "gpt-5-nano"
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_1 = "gpt-5.1"
    GPT_56_LUNA = "gpt-5.6-luna"
    GPT_56_TERRA = "gpt-5.6-terra"
    GPT_56_SOL = "gpt-5.6-sol"


class AnthropicModelName(StrEnum):
    HAIKU_45 = "claude-haiku-4-5"
    SONNET_45 = "claude-sonnet-4-5"
    SONNET_5 = "claude-sonnet-5"


class GoogleModelName(StrEnum):
    GEMINI_31_FLASH_LITE = "gemini-3.1-flash-lite"
    GEMINI_35_FLASH = "gemini-3.5-flash"
    GEMINI_35_FLASH_LITE = "gemini-3.5-flash-lite"
    GEMINI_36_FLASH = "gemini-3.6-flash"
    GEMINI_37_FLASH = "gemini-3.7-flash"
    GEMINI_38_FLASH = "gemini-3.8-flash"
    GEMINI_31_PRO_PREVIEW = "gemini-3.1-pro-preview"


class OllamaModelName(StrEnum):
    OLLAMA_GENERIC = "ollama"


class FakeModelName(StrEnum):
    FAKE = "fake"


type AllModelEnum = (
    OpenAIModelName
    | AnthropicModelName
    | GoogleModelName
    | OllamaModelName
    | FakeModelName
)


class FakeToolModel(FakeListChatModel):
    """Offline model supporting tool binding and structured output for deterministic testing."""

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> "FakeToolModel":
        return self


type ModelT = Any


def _resolve_provider_and_endpoint(
    provider: Provider | str | None, model_name: str
) -> tuple[Provider, str, SecretStr | None]:
    if agent_settings.USE_FAKE_MODEL or model_name == FakeModelName.FAKE:
        return Provider.FAKE, "", None

    prov_str = (str(provider) if provider else "").lower()
    if not prov_str:
        if model_name.startswith("claude"):
            prov_str = Provider.ANTHROPIC
        elif model_name.startswith("gemini"):
            prov_str = Provider.GOOGLE
        elif model_name.startswith("ollama"):
            prov_str = Provider.OLLAMA
        else:
            prov_str = agent_settings.DEFAULT_PROVIDER.lower()

    if prov_str == Provider.OLLAMA:
        return (
            Provider.OLLAMA,
            agent_settings.OLLAMA_BASE_URL,
            SecretStr("ollama-local"),
        )
    if prov_str == Provider.ANTHROPIC:
        key = agent_settings.ANTHROPIC_API_KEY or agent_settings.effective_api_key
        base_url = agent_settings.MODEL_BASE_URL
        return Provider.ANTHROPIC, base_url, key
    if prov_str == Provider.GOOGLE:
        key = agent_settings.GOOGLE_API_KEY or agent_settings.effective_api_key
        base_url = agent_settings.MODEL_BASE_URL
        return Provider.GOOGLE, base_url, key

    key = agent_settings.effective_api_key
    base_url = agent_settings.COMPATIBLE_BASE_URL or agent_settings.MODEL_BASE_URL
    return Provider.OPENAI, base_url, key


@cache
def get_llm(
    model_name: AllModelEnum | str | None = None,
    *,
    provider: Provider | str | None = None,
    temperature: float | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> ModelT:
    """Initialize and return a configured chat model across OpenAI, Anthropic, Gemini, local Ollama, or Fake."""
    selected = str(
        model_name
        or (FakeModelName.FAKE if agent_settings.USE_FAKE_MODEL else agent_settings.DEFAULT_MODEL)
    )
    if (
        not agent_settings.USE_FAKE_MODEL
        and agent_settings.AVAILABLE_MODELS
        and selected not in agent_settings.AVAILABLE_MODELS
    ):
        raise ConfigurationError(
            f"Model '{selected}' is not in AVAILABLE_MODELS",
            details={"selected": selected, "available": sorted(agent_settings.AVAILABLE_MODELS)},
        )

    resolved_provider, base_url, api_key = _resolve_provider_and_endpoint(provider, selected)
    if resolved_provider == Provider.FAKE or ChatOpenAI is None:
        return FakeToolModel(
            responses=["Xin chào từ HercFit AI Agent! Tôi đã xử lý yêu cầu của bạn."]
        )

    if api_key is None:
        raise ConfigurationError(
            f"API key is not configured for provider '{resolved_provider}' and model '{selected}'."
        )

    try:
        return ChatOpenAI(
            model=selected,
            api_key=api_key,
            base_url=base_url,
            temperature=(
                temperature if temperature is not None else agent_settings.MODEL_TEMPERATURE
            ),
            streaming=True,
            timeout=timeout if timeout is not None else agent_settings.MODEL_TIMEOUT_SECONDS,
            max_retries=(
                max_retries if max_retries is not None else agent_settings.MODEL_MAX_RETRIES
            ),
        )
    except Exception as exc:
        raise LLMProviderError(
            f"Failed to initialize LLM '{selected}' ({resolved_provider}): {exc}"
        ) from exc


get_model = get_llm


@cache
def get_embeddings() -> Any:
    """Return an OpenAI-compatible embeddings client for pgvector long-term memory."""
    if not agent_settings.EMBEDDING_MODEL:
        raise ConfigurationError("Set EMBEDDING_MODEL in .env to enable vector semantic memory.")
    api_key = agent_settings.effective_api_key
    if api_key is None:
        raise ConfigurationError("Set MODEL_API_KEY or OPENAI_API_KEY before using embeddings.")
    if OpenAIEmbeddings is None or not HAS_LANGCHAIN:
        raise ConfigurationError("langchain-openai is required to initialize OpenAIEmbeddings.")
    return OpenAIEmbeddings(
        model=agent_settings.EMBEDDING_MODEL,
        api_key=api_key,
        base_url=agent_settings.MODEL_BASE_URL,
        check_embedding_ctx_length=False,
        request_timeout=agent_settings.MODEL_TIMEOUT_SECONDS,
        max_retries=agent_settings.MODEL_MAX_RETRIES,
    )


@cache
def get_langsmith_client() -> Any:
    """Initialize an explicit LangSmith client from agent_settings."""
    if agent_settings.LANGSMITH_API_KEY is None:
        raise ConfigurationError("Set LANGSMITH_API_KEY before using LangSmith client.")
    from langsmith import Client as LangSmithClient

    return LangSmithClient(
        api_url=agent_settings.LANGSMITH_ENDPOINT,
        api_key=agent_settings.LANGSMITH_API_KEY.get_secret_value(),
    )


def get_tracing_callbacks() -> list[Any]:
    """Return LangChain tracers if LANGSMITH_TRACING is enabled."""
    if not agent_settings.LANGSMITH_TRACING or agent_settings.LANGSMITH_API_KEY is None or not HAS_LANGCHAIN:
        return []
    return [
        LangChainTracer(
            project_name=agent_settings.LANGSMITH_PROJECT,
            client=get_langsmith_client(),
        )
    ]

