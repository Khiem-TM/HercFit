from langchain_openai import ChatOpenAI
from agentic.core.app.config import AgentSettings
from agentic.core.providers.fpt import FPTChatOpenAI
from agentic.services import mode

ROLE_TIMEOUTS = {
    'decision': 'ROUTING_TIMEOUT_SECONDS', 'tool': 'TOOL_TIMEOUT_SECONDS', 'clarify': 'ROUTING_TIMEOUT_SECONDS',
    'summary': 'ROUTING_TIMEOUT_SECONDS', 'response': 'RESPONSE_TIMEOUT_SECONDS', 'research': 'RESEARCH_TIMEOUT_SECONDS',
}


class WithFallback:

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback
        self.metadata = getattr(primary, 'metadata', None)

    def with_structured_output(self, *args, **kwargs):
        return self.primary.with_structured_output(*args, **kwargs).with_fallbacks(
            [self.fallback.with_structured_output(*args, **kwargs)])

    def bind_tools(self, *args, **kwargs):
        return self.primary.bind_tools(*args, **kwargs).with_fallbacks([self.fallback.bind_tools(*args, **kwargs)])

    async def ainvoke(self, *args, **kwargs):
        return await self.primary.with_fallbacks([self.fallback]).ainvoke(*args, **kwargs)


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

    def _client(self, provider, name, api_key, base_url, role, policy=mode.POLICIES[mode.FULL]):
        settings = self.settings
        streaming_role = role == 'response' and getattr(settings, 'STREAM_RESPONSE_TOKENS', True)
        timeout = getattr(settings, ROLE_TIMEOUTS.get(role, ''), None) or settings.MODEL_TIMEOUT_SECONDS
        # Chế độ trò chuyện có thể kéo dài timeout (Plan suy luận lâu hơn), không bao giờ rút ngắn.
        timeout = max(timeout, policy.timeouts.get(role, 0))
        model_class = FPTChatOpenAI if provider == 'fpt' else ChatOpenAI
        effort = (policy.efforts.get(role) or getattr(
            settings, {'research': 'RESEARCH_REASONING_EFFORT', 'tool': 'TOOL_REASONING_EFFORT'}.get(role, ''), None)) \
            if provider == 'fpt' else None
        return model_class(
            model=name, api_key=api_key, base_url=base_url, timeout=timeout,
            temperature=0.0, max_retries=getattr(settings, 'MODEL_MAX_RETRIES', 1),
            stream_usage=bool(streaming_role and getattr(settings, 'MODEL_STREAM_USAGE', False)),
            disable_streaming=not streaming_role,
            metadata={'hercfit_provider': provider, 'hercfit_model': name, 'model_role': role},
            **({'reasoning_effort': effort} if effort else {}),
        )

    def get(self, role):
        # Một client cho mỗi (vai trò, chế độ của lượt chạy): effort và timeout là tham số dựng client.
        policy = mode.policy()
        cached = (role, policy.name)
        if cached not in self.cache:
            settings = self.settings
            name = self.model_name(role)
            primary = self._client(settings.DEFAULT_PROVIDER, name, settings.model_api_key, settings.model_base_url,
                                   role, policy)
            fallback_name = getattr(settings, 'FALLBACK_MODEL', None)
            if fallback_name:
                provider = getattr(settings, 'FALLBACK_PROVIDER', None) or 'openai_compatible'
                base_url = getattr(settings, 'FALLBACK_BASE_URL', None) or (
                    settings.FPT_BASE_URL if provider == 'fpt' else settings.MODEL_BASE_URL)
                key = getattr(settings, 'FALLBACK_API_KEY', None) or settings.model_api_key
                self.cache[cached] = WithFallback(primary, self._client(provider, fallback_name, key, base_url, role, policy))
            else:
                self.cache[cached] = primary
        return self.cache[cached]
