"""Kết nối dùng chung tới nhà cung cấp kiểu OpenAI (embedding và rerank cùng endpoint, cùng khoá)."""
import httpx

from agentic.observability import annotate


def provider_http(settings, timeout, transport=None):
    settings.check_embedding()
    key = settings.EMBEDDING_API_KEY
    return httpx.AsyncClient(
        base_url=settings.EMBEDDING_BASE_URL.rstrip('/') + '/',
        headers={'Authorization': 'Bearer ' + key.get_secret_value()} if key else {},
        timeout=timeout, transport=transport, follow_redirects=False,
    )


def record_usage(model, provider, tokens):
    """Gắn model và số token (khi nhà cung cấp trả về) vào span đang mở; giá chưa biết."""
    annotate(hercfit_model=model, hercfit_provider=provider, cost_status='unknown')
    if type(tokens) is int and tokens >= 0:
        annotate(usage_metadata={'input_tokens': tokens, 'output_tokens': 0, 'total_tokens': tokens})
