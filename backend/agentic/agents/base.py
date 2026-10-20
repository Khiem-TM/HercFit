"""Base class and protocol standard for all specialized Agents in HercFit."""

from abc import ABC, abstractmethod
from typing import Any

from config.settings import agent_settings, load_agent_yaml_config
from core.llm import (
    AnyMessage,
    FakeToolModel,
    HumanMessage,
    ModelT,
    RunnableConfig,
    SystemMessage,
    get_llm,
)
from core.state import AgentState


class BaseAgent(ABC):
    """Abstract base class for all agents in the Multi-Agent workflow."""

    name: str = "base_agent"
    description: str = "Base agent"
    default_system_prompt: str = "You are a helpful AI assistant for HercFit."

    def __init__(
        self,
        *,
        model_name: str | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        yaml_cfg = load_agent_yaml_config()
        agent_cfg = (yaml_cfg.get("agents") or {}).get(self.name, {})
        defaults_cfg = yaml_cfg.get("defaults") or {}

        self.model_name: str = (
            model_name
            or agent_cfg.get("model")
            or defaults_cfg.get("model")
            or agent_settings.DEFAULT_MODEL
        )
        self.temperature: float = (
            temperature
            if temperature is not None
            else float(
                agent_cfg.get(
                    "temperature",
                    defaults_cfg.get("temperature", agent_settings.MODEL_TEMPERATURE),
                )
            )
        )
        self.system_prompt: str = (
            system_prompt
            or agent_cfg.get("system_prompt")
            or self.default_system_prompt
        )
        self.tools: list[Any] = list(tools) if tools is not None else []

    def get_model(self, override_model: str | None = None) -> ModelT:
        model = get_llm(
            override_model or self.model_name,
            temperature=self.temperature,
        )
        if self.tools and hasattr(model, "bind_tools"):
            return model.bind_tools(self.tools)
        return model

    def is_fake_model(self, model: ModelT | None = None) -> bool:
        target = model or get_llm(self.model_name, temperature=self.temperature)
        return isinstance(target, FakeToolModel) or agent_settings.USE_FAKE_MODEL

    def build_messages(self, state: AgentState) -> list[AnyMessage]:
        history = list(state.get("messages") or [])
        return [SystemMessage(content=self.system_prompt), *history]

    @staticmethod
    def latest_user_text(state: AgentState) -> str:
        for msg in reversed(state.get("messages") or []):
            if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
                return str(msg.content)
        return ""

    @abstractmethod
    async def ainvoke(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        """Execute agent node logic and return partial AgentState updates."""
        raise NotImplementedError
