from langchain_openai import ChatOpenAI
from agentic.config.settings import AgentSettings
from agentic.clients.fpt import FPTChatOpenAI

class Models:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.cache = {}

    def get(self, role):
        if role not in self.cache:
            name = getattr(self.settings, role.upper() + '_MODEL') or self.settings.DEFAULT_MODEL
            model_class = FPTChatOpenAI if self.settings.DEFAULT_PROVIDER == 'fpt' else ChatOpenAI
            self.cache[role] = model_class(
                model=name, api_key=self.settings.model_api_key,
                base_url=self.settings.model_base_url, timeout=self.settings.MODEL_TIMEOUT_SECONDS,
                temperature=0.0, max_retries=1, stream_usage=False,
            )
        return self.cache[role]
