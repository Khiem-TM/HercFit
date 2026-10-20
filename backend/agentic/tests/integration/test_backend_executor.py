"""Integration tests using mocked Backend HTTP transport to verify BackendClient and BackendExecutorAgent."""

import json
import unittest

import httpx

from agents.backend_executor_agent import BackendExecutorAgent
from clients.backend_client import BackendClient
from core.exceptions import BackendAPIError
from core.llm import HumanMessage


def _mock_backend_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/profile" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "athlete@hercfit.io",
                "fullname": "HercFit Athlete",
                "is_onboarding": True,
            },
        )
    if path == "/api/goals/current" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "id": "22222222-2222-2222-2222-222222222222",
                "title": "Giảm mỡ còn 68kg",
                "status": "active",
                "targets": {"weight_kg": {"value": 68, "unit": "kg"}},
            },
        )
    if path == "/api/body-metrics" and request.method == "POST":
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            201,
            json={
                "id": "33333333-3333-3333-3333-333333333333",
                "weight_kg": body["weight_kg"],
                "is_active": True,
            },
        )
    if path == "/api/foods" and request.method == "GET":
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "44444444-4444-4444-4444-444444444444",
                        "name_vi": "Ức gà áp chảo",
                        "calories_kcal": 165.0,
                        "protein_g": 31.0,
                    }
                ]
            },
        )
    return httpx.Response(404, json={"detail": "Not found"})


class IntegrationBackendExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        transport = httpx.MockTransport(_mock_backend_handler)
        self.client = BackendClient(
            base_url="http://mock-backend:8080",
            transport=transport,
            max_retries=2,
        )
        self.agent = BackendExecutorAgent(backend_client=self.client)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_backend_client_fetch_profile_and_goal(self):
        profile = await self.client.get_user_profile(auth_token="jwt-token")
        self.assertEqual(profile.email, "athlete@hercfit.io")

        goal = await self.client.get_current_goal(auth_token="jwt-token")
        self.assertIsNotNone(goal)
        self.assertEqual(goal.title, "Giảm mỡ còn 68kg")

    async def test_backend_client_raises_backend_api_error_on_404(self):
        with self.assertRaises(BackendAPIError) as ctx:
            await self.client.request("GET", "/api/non-existent")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_backend_executor_agent_logs_body_metrics(self):
        state = {
            "messages": [HumanMessage(content="Hãy ghi nhận cân nặng hôm nay là 71.5kg")],
            "auth_token": "jwt-token",
            "tool_outputs": [],
            "context": {},
        }
        updated = await self.agent.ainvoke(state)
        self.assertEqual(updated["next_agent"], "FINISH")
        self.assertEqual(len(updated["tool_outputs"]), 1)
        self.assertEqual(updated["tool_outputs"][0]["tool"], "log_body_metrics")
        self.assertEqual(updated["tool_outputs"][0]["output"]["weight_kg"], 71.5)

    async def test_backend_executor_agent_searches_foods(self):
        state = {
            "messages": [HumanMessage(content="Tìm món ăn ức gà cho tôi")],
            "auth_token": "jwt-token",
            "tool_outputs": [],
            "context": {},
        }
        updated = await self.agent.ainvoke(state)
        self.assertEqual(updated["tool_outputs"][0]["tool"], "search_foods")
        items = updated["tool_outputs"][0]["output"]["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name_vi"], "Ức gà áp chảo")


if __name__ == "__main__":
    unittest.main()
