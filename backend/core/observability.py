"""Explicit LangSmith clients so .env settings work without mutating os.environ."""

from functools import cache

from langchain_core.tracers.langchain import LangChainTracer
from langsmith import Client

from core.settings import settings


@cache
def get_langsmith_client() -> Client:
    if settings.LANGSMITH_API_KEY is None:
        raise ValueError("Set LANGSMITH_API_KEY before using LangSmith")
    return Client(
        api_url=settings.LANGSMITH_ENDPOINT,
        api_key=settings.LANGSMITH_API_KEY.get_secret_value(),
    )


def get_tracing_callbacks() -> list[LangChainTracer]:
    if not settings.LANGSMITH_TRACING:
        return []
    return [LangChainTracer(project_name=settings.LANGSMITH_PROJECT, client=get_langsmith_client())]
