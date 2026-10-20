"""Registry exporting available tools for HercFit specialized agents."""

from typing import Any

from tools.decorators import tool_monitor
from tools.definitions.backend_tools import (
    BACKEND_TOOLS,
    fetch_current_goal,
    fetch_latest_body_metrics,
    fetch_progress_overview,
    fetch_user_profile,
    get_current_goal_tool,
    get_latest_body_metrics_tool,
    get_progress_overview_tool,
    get_shared_backend_client,
    get_user_profile_tool,
    log_body_metrics_tool,
    record_body_metric,
    search_backend_exercises,
    search_backend_foods,
    search_exercises_tool,
    search_foods_tool,
    set_shared_backend_client,
)
from tools.definitions.system_tools import (
    SYSTEM_TOOLS,
    calculate_health_metrics_tool,
    compute_health_metrics,
    evaluate_math,
    evaluate_math_expression_tool,
    search_fitness_knowledge,
    search_knowledge_base_tool,
)

TOOL_REGISTRY: dict[str, Any] = {t.name: t for t in [*SYSTEM_TOOLS, *BACKEND_TOOLS]}


def get_system_tools() -> list[Any]:
    return list(SYSTEM_TOOLS)


def get_backend_tools() -> list[Any]:
    return list(BACKEND_TOOLS)


def get_all_tools() -> list[Any]:
    return list(TOOL_REGISTRY.values())


__all__ = [
    "BACKEND_TOOLS",
    "SYSTEM_TOOLS",
    "TOOL_REGISTRY",
    "calculate_health_metrics_tool",
    "compute_health_metrics",
    "evaluate_math",
    "evaluate_math_expression_tool",
    "fetch_current_goal",
    "fetch_latest_body_metrics",
    "fetch_progress_overview",
    "fetch_user_profile",
    "get_all_tools",
    "get_backend_tools",
    "get_current_goal_tool",
    "get_latest_body_metrics_tool",
    "get_progress_overview_tool",
    "get_shared_backend_client",
    "get_system_tools",
    "get_user_profile_tool",
    "log_body_metrics_tool",
    "record_body_metric",
    "search_backend_exercises",
    "search_backend_foods",
    "search_exercises_tool",
    "search_fitness_knowledge",
    "search_foods_tool",
    "search_knowledge_base_tool",
    "set_shared_backend_client",
    "tool_monitor",
]

