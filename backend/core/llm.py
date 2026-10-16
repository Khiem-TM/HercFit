"""Factories sharing a single API key and OpenAI-compatible endpoint."""

from functools import cache

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr
from agents.schema.models import AllModelEnum

from core.settings import settings


class FakeToolModel(FakeListChatModel):
    """Offline model retained for explicit development smoke tests."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


type ModelT = ChatOpenAI | FakeToolModel


def _require_model_key() -> SecretStr:
    if settings.MODEL_API_KEY is None:
        raise ValueError("Set MODEL_API_KEY in backend/.env before using the model endpoint")
    return settings.MODEL_API_KEY


@cache
def get_model(model_name: AllModelEnum | str | None = None, /) -> ModelT:
    """Return the configured model; reject unconfigured names before making requests."""
    selected = model_name or ("fake" if settings.USE_FAKE_MODEL else settings.DEFAULT_MODEL)
    if selected not in settings.AVAILABLE_MODELS:
        raise ValueError(
            f"Model '{selected}' is not configured; allowed: {settings.AVAILABLE_MODELS}"
        )
    if settings.USE_FAKE_MODEL:
        return FakeToolModel(responses=["This is a test response from the fake model."])
    return ChatOpenAI(
        model=str(selected),
        api_key=_require_model_key(),
        base_url=settings.MODEL_BASE_URL,
        streaming=True,
        timeout=settings.MODEL_TIMEOUT_SECONDS,
        max_retries=settings.MODEL_MAX_RETRIES,
    )


@cache
def get_embeddings() -> OpenAIEmbeddings:
    """Use the same endpoint/key for optional pgvector semantic memory."""
    if not settings.EMBEDDING_MODEL:
        raise ValueError("Set EMBEDDING_MODEL to enable semantic memory")
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=_require_model_key(),
        base_url=settings.MODEL_BASE_URL,
        # Do not require a local tokenizer for arbitrary compatible model names.
        check_embedding_ctx_length=False,
        request_timeout=settings.MODEL_TIMEOUT_SECONDS,
        max_retries=settings.MODEL_MAX_RETRIES,
    )
