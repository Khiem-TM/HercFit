from typing import Any

try:
    from agents.agents import (
        DEFAULT_AGENT,
        AgentGraph,
        AgentGraphLike,
        get_agent,
        get_all_agent_info,
        load_agent,
    )
except Exception:
    DEFAULT_AGENT = "default"
    AgentGraph = Any
    AgentGraphLike = Any

    def get_agent(*args: Any, **kwargs: Any) -> Any:
        return None

    def get_all_agent_info() -> list[Any]:
        return []

    async def load_agent(*args: Any, **kwargs: Any) -> None:
        pass

__all__ = [
    "get_agent",
    "load_agent",
    "get_all_agent_info",
    "DEFAULT_AGENT",
    "AgentGraph",
    "AgentGraphLike",
]
