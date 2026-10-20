"""SDK wrapper interacting directly with internal HercFit CRUD Backend API endpoints."""

from typing import Any

from clients.base_http import BaseHTTPClient
from clients.schemas import (
    BodyMetricDTO,
    CatalogItemDTO,
    GoalDTO,
    ProgressOverviewDTO,
    UserProfileDTO,
)


class BackendClient(BaseHTTPClient):
    """High-level async SDK client for HercFit CRUD Backend routes."""

    async def check_health(self) -> dict[str, Any]:
        return await self.request("GET", "/health")

    async def get_user_profile(self, *, auth_token: str | None = None) -> UserProfileDTO:
        data = await self.request("GET", "/api/profile", auth_token=auth_token)
        return UserProfileDTO.model_validate(data)

    async def update_user_profile(
        self, payload: dict[str, Any], *, auth_token: str | None = None
    ) -> UserProfileDTO:
        data = await self.request(
            "PATCH", "/api/profile", json_body=payload, auth_token=auth_token
        )
        return UserProfileDTO.model_validate(data)

    async def get_current_goal(self, *, auth_token: str | None = None) -> GoalDTO | None:
        data = await self.request("GET", "/api/goals/current", auth_token=auth_token)
        if not data:
            return None
        return GoalDTO.model_validate(data)

    async def get_latest_body_metrics(
        self, *, auth_token: str | None = None
    ) -> BodyMetricDTO | None:
        data = await self.request(
            "GET", "/api/body-metrics/latest", auth_token=auth_token
        )
        if not data:
            return None
        return BodyMetricDTO.model_validate(data)

    async def create_body_metric(
        self, payload: dict[str, Any], *, auth_token: str | None = None
    ) -> BodyMetricDTO:
        data = await self.request(
            "POST", "/api/body-metrics", json_body=payload, auth_token=auth_token
        )
        return BodyMetricDTO.model_validate(data)

    async def get_progress_overview(
        self, *, auth_token: str | None = None
    ) -> ProgressOverviewDTO:
        data = await self.request("GET", "/api/progress", auth_token=auth_token)
        return ProgressOverviewDTO.model_validate(data)

    async def search_foods(
        self,
        *,
        search: str | None = None,
        limit: int = 10,
        auth_token: str | None = None,
    ) -> list[CatalogItemDTO]:
        params: dict[str, Any] = {"limit": limit}
        if search:
            params["search"] = search
        data = await self.request(
            "GET", "/api/foods", params=params, auth_token=auth_token
        )
        items = data.get("items", data) if isinstance(data, dict) else data
        return [CatalogItemDTO.model_validate(item) for item in (items or [])]

    async def search_exercises(
        self,
        *,
        search: str | None = None,
        limit: int = 10,
        auth_token: str | None = None,
    ) -> list[CatalogItemDTO]:
        params: dict[str, Any] = {"limit": limit}
        if search:
            params["search"] = search
        data = await self.request(
            "GET", "/api/exercises", params=params, auth_token=auth_token
        )
        items = data.get("items", data) if isinstance(data, dict) else data
        return [CatalogItemDTO.model_validate(item) for item in (items or [])]

