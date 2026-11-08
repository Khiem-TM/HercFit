from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from agentic.core import roster
from agentic.core.app.config import AgentSettings
from agentic.core.providers.fpt import FPTChatOpenAI
from agentic.services import mode

ROLE_TIMEOUTS = {
    'decision': 'ROUTING_TIMEOUT_SECONDS', 'tool': 'TOOL_TIMEOUT_SECONDS', 'clarify': 'ROUTING_TIMEOUT_SECONDS',
    'summary': 'ROUTING_TIMEOUT_SECONDS', 'response': 'RESPONSE_TIMEOUT_SECONDS', 'research': 'RESEARCH_TIMEOUT_SECONDS',
}


def _present(value):
    # Adapter FPT dựng output có cấu trúc bằng function calling: model không gọi hàm thì parser trả None.
    if value is None:
        raise ValueError('Structured output missing')
    return value


class WithFallback:
    """Model chính rồi lần lượt các model dự phòng. strict: output có cấu trúc rỗng cũng chuyển sang dự phòng
    (model riêng của agent nâng lên model của vai trò)."""

    def __init__(self, primary, *fallbacks, strict=False):
        self.primary, self.fallbacks, self.strict = primary, fallbacks, strict
        self.metadata = getattr(primary, 'metadata', None)

    def with_structured_output(self, *args, **kwargs):
        primary = self.primary.with_structured_output(*args, **kwargs)
        if self.strict:
            primary = primary | RunnableLambda(_present)
        return primary.with_fallbacks([model.with_structured_output(*args, **kwargs) for model in self.fallbacks])

    def bind_tools(self, *args, **kwargs):
        return self.primary.bind_tools(*args, **kwargs).with_fallbacks(
            [model.bind_tools(*args, **kwargs) for model in self.fallbacks])

    async def ainvoke(self, *args, **kwargs):
        return await self.primary.with_fallbacks(list(self.fallbacks)).ainvoke(*args, **kwargs)


class Models:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.cache = {}

    def model_name(self, role):
        settings = self.settings
        name = getattr(settings, role.upper() + '_MODEL', None)
        if not name and role == 'clarify':
            name = getattr(settings, 'RESPONSE_MODEL', None)
        return name or settings.DEFAULT_MODEL

    def _client(self, provider, name, api_key, base_url, role, policy=mode.POLICIES[mode.FULL], retries=None, cap=None):
        settings = self.settings
        streaming_role = role == 'response' and getattr(settings, 'STREAM_RESPONSE_TOKENS', True)
        timeout = getattr(settings, ROLE_TIMEOUTS.get(role, ''), None) or settings.MODEL_TIMEOUT_SECONDS
        # Chế độ trò chuyện có thể kéo dài timeout (Plan suy luận lâu hơn), không bao giờ rút ngắn.
        timeout = max(timeout, policy.timeouts.get(role, 0))
        if cap:
            timeout = min(timeout, cap)  # model riêng của agent: lỗi sớm để nâng cấp, không chờ hết timeout vai trò
        model_class = FPTChatOpenAI if provider == 'fpt' else ChatOpenAI
        effort = (policy.efforts.get(role) or getattr(
            settings, {'research': 'RESEARCH_REASONING_EFFORT', 'tool': 'TOOL_REASONING_EFFORT'}.get(role, ''), None)) \
            if provider == 'fpt' else None
        return model_class(
            model=name, api_key=api_key, base_url=base_url, timeout=timeout,
            temperature=0.0, max_retries=getattr(settings, 'MODEL_MAX_RETRIES', 1) if retries is None else retries,
            stream_usage=bool(streaming_role and getattr(settings, 'MODEL_STREAM_USAGE', False)),
            disable_streaming=not streaming_role,
            metadata={'hercfit_provider': provider, 'hercfit_model': name, 'model_role': role},
            **({'reasoning_effort': effort} if effort else {}),
        )

    def get(self, role):
        # Một client cho mỗi (vai trò, chế độ của lượt chạy, model riêng của agent): effort và timeout là tham số dựng client.
        policy = mode.policy()
        name = self.model_name(role)
        own = roster.assigned_model(self.settings, role)
        own = own if own != name else None
        cached = (role, policy.name, own)
        if cached not in self.cache:
            settings = self.settings
            primary = self._client(settings.DEFAULT_PROVIDER, name, settings.model_api_key, settings.model_base_url,
                                   role, policy)
            fallbacks = []
            fallback_name = getattr(settings, 'FALLBACK_MODEL', None)
            if fallback_name:
                provider = getattr(settings, 'FALLBACK_PROVIDER', None) or 'openai_compatible'
                base_url = getattr(settings, 'FALLBACK_BASE_URL', None) or (
                    settings.FPT_BASE_URL if provider == 'fpt' else settings.MODEL_BASE_URL)
                key = getattr(settings, 'FALLBACK_API_KEY', None) or settings.model_api_key
                fallbacks.append(self._client(provider, fallback_name, key, base_url, role, policy))
            if own:
                # Model riêng của agent thử một lần (không retry): lỗi, timeout hoặc output có cấu trúc rỗng nâng ngay lên
                # model của vai trò, nên một model nhỏ không bao giờ làm lượt kém hơn cấu hình mặc định.
                assigned = self._client(settings.DEFAULT_PROVIDER, own, settings.model_api_key, settings.model_base_url,
                                        role, policy, retries=0, cap=getattr(settings, 'AGENT_MODEL_TIMEOUT_SECONDS', None))
                self.cache[cached] = WithFallback(assigned, primary, *fallbacks, strict=True)
            elif fallbacks:
                self.cache[cached] = WithFallback(primary, *fallbacks)
            else:
                self.cache[cached] = primary
        return self.cache[cached]
