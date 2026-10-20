"""Tools interacting with the internal HercFit CRUD Backend service via BackendClient."""

from typing import Any

from core.llm import tool

from clients.backend_client import BackendClient
from tools.decorators import tool_monitor
from tools.schemas.auth_schemas import AuthContextInput
from tools.schemas.user_schemas import BodyMetricLogInput, CatalogSearchInput

_default_backend_client: BackendClient | None = None


def get_shared_backend_client() -> BackendClient:
    global _default_backend_client
    if _default_backend_client is None:
        _default_backend_client = BackendClient()
    return _default_backend_client


def set_shared_backend_client(client: BackendClient | None) -> None:
    global _default_backend_client
    _default_backend_client = client


@tool_monitor(name="fetch_user_profile", max_retries=2)
async def fetch_user_profile(
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Fetch the authenticated user's profile from HercFit Backend."""
    backend = client or get_shared_backend_client()
    profile = await backend.get_user_profile(auth_token=auth_token)
    return profile.model_dump(mode="json")


@tool_monitor(name="fetch_current_goal", max_retries=2)
async def fetch_current_goal(
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Fetch the authenticated user's active fitness goal from HercFit Backend."""
    backend = client or get_shared_backend_client()
    goal = await backend.get_current_goal(auth_token=auth_token)
    return goal.model_dump(mode="json") if goal else {"status": "no_active_goal"}


@tool_monitor(name="fetch_latest_body_metrics", max_retries=2)
async def fetch_latest_body_metrics(
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Fetch the latest body metric snapshot for the user."""
    backend = client or get_shared_backend_client()
    metric = await backend.get_latest_body_metrics(auth_token=auth_token)
    return metric.model_dump(mode="json") if metric else {"status": "no_metrics_found"}


@tool_monitor(name="record_body_metric", max_retries=1)
async def record_body_metric(
    weight_kg: float,
    height_cm: float | None = None,
    body_fat_pct: float | None = None,
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Record a new body metric entry in HercFit Backend."""
    validated = BodyMetricLogInput(
        weight_kg=weight_kg,
        height_cm=height_cm,
        body_fat_pct=body_fat_pct,
        auth_token=auth_token,
    )
    payload: dict[str, Any] = {"weight_kg": validated.weight_kg}
    if validated.height_cm is not None:
        payload["height_cm"] = validated.height_cm
    if validated.body_fat_pct is not None:
        payload["body_fat_pct"] = validated.body_fat_pct

    backend = client or get_shared_backend_client()
    created = await backend.create_body_metric(
        payload, auth_token=validated.auth_token
    )
    return created.model_dump(mode="json")


@tool_monitor(name="fetch_progress_overview", max_retries=2)
async def fetch_progress_overview(
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Fetch progress overview from HercFit Backend."""
    backend = client or get_shared_backend_client()
    progress = await backend.get_progress_overview(auth_token=auth_token)
    return progress.model_dump(mode="json")


@tool_monitor(name="search_backend_foods", max_retries=2)
async def search_backend_foods(
    search: str,
    limit: int = 5,
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> list[dict[str, Any]]:
    """Search food items from HercFit Backend catalog."""
    validated = CatalogSearchInput(search=search, limit=limit, auth_token=auth_token)
    backend = client or get_shared_backend_client()
    items = await backend.search_foods(
        search=validated.search,
        limit=validated.limit,
        auth_token=validated.auth_token,
    )
    return [item.model_dump(mode="json") for item in items]


@tool_monitor(name="search_backend_exercises", max_retries=2)
async def search_backend_exercises(
    search: str,
    limit: int = 5,
    auth_token: str | None = None,
    client: BackendClient | None = None,
) -> list[dict[str, Any]]:
    """Search exercise items from HercFit Backend catalog."""
    validated = CatalogSearchInput(search=search, limit=limit, auth_token=auth_token)
    backend = client or get_shared_backend_client()
    items = await backend.search_exercises(
        search=validated.search,
        limit=validated.limit,
        auth_token=validated.auth_token,
    )
    return [item.model_dump(mode="json") for item in items]


@tool("get_user_profile", args_schema=AuthContextInput)
async def get_user_profile_tool(
    user_id: str | None = None, auth_token: str | None = None
) -> dict[str, Any]:
    """Retrieve the user's profile from HercFit Backend."""
    return await fetch_user_profile(auth_token=auth_token)


@tool("get_current_goal", args_schema=AuthContextInput)
async def get_current_goal_tool(
    user_id: str | None = None, auth_token: str | None = None
) -> dict[str, Any]:
    """Retrieve the user's current fitness goal from HercFit Backend."""
    return await fetch_current_goal(auth_token=auth_token)


@tool("get_latest_body_metrics", args_schema=AuthContextInput)
async def get_latest_body_metrics_tool(
    user_id: str | None = None, auth_token: str | None = None
) -> dict[str, Any]:
    """Retrieve the user's latest body weight and composition metrics."""
    return await fetch_latest_body_metrics(auth_token=auth_token)


@tool("log_body_metrics", args_schema=BodyMetricLogInput)
async def log_body_metrics_tool(
    weight_kg: float,
    height_cm: float | None = None,
    body_fat_pct: float | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Log a new body weight/fat measurement to HercFit Backend."""
    return await record_body_metric(
        weight_kg=weight_kg,
        height_cm=height_cm,
        body_fat_pct=body_fat_pct,
        auth_token=auth_token,
    )


@tool("get_progress_overview", args_schema=AuthContextInput)
async def get_progress_overview_tool(
    user_id: str | None = None, auth_token: str | None = None
) -> dict[str, Any]:
    """Retrieve the user's overall fitness and nutrition progress summary."""
    return await fetch_progress_overview(auth_token=auth_token)


@tool("search_foods", args_schema=CatalogSearchInput)
async def search_foods_tool(
    search: str, limit: int = 5, auth_token: str | None = None
) -> list[dict[str, Any]]:
    """Search the HercFit food catalog by keyword."""
    return await search_backend_foods(
        search=search, limit=limit, auth_token=auth_token
    )


@tool("search_exercises", args_schema=CatalogSearchInput)
async def search_exercises_tool(
    search: str, limit: int = 5, auth_token: str | None = None
) -> list[dict[str, Any]]:
    """Search the HercFit exercise catalog by keyword."""
    return await search_backend_exercises(
        search=search, limit=limit, auth_token=auth_token
    )


BACKEND_TOOLS = [
    get_user_profile_tool,
    get_current_goal_tool,
    get_latest_body_metrics_tool,
    log_body_metrics_tool,
    get_progress_overview_tool,
    search_foods_tool,
    search_exercises_tool,
]
