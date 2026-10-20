"""Evaluation tests verifying RouterAgent intent classification, workflow routing, and FastAPI chat API."""

import unittest

import httpx

from agents.router_agent import RouterAgent
from clients.backend_client import BackendClient
from core.llm import HumanMessage
from graph.workflow import compile_agent_workflow
from main import create_agentic_app


def _eval_backend_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/goals/current":
        return httpx.Response(
            200,
            json={
                "id": "goal-123",
                "title": "Tăng cơ lên 75kg",
                "status": "active",
            },
        )
    return httpx.Response(
        200,
        json={
            "id": "user-123",
            "email": "eval@hercfit.io",
            "fullname": "Eval User",
        },
    )


class EvaluationAgentRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.router = RouterAgent()
        self.mock_backend = BackendClient(
            base_url="http://mock-backend:8080",
            transport=httpx.MockTransport(_eval_backend_handler),
        )
        self.workflow = compile_agent_workflow(backend_client=self.mock_backend)

    async def asyncTearDown(self):
        await self.mock_backend.close()

    async def test_router_intent_classification_accuracy(self):
        cases = [
            (
                "Tính giúp tôi BMI và TDEE cho nam 75kg, cao 178cm, 24 tuổi",
                "data_analysis",
                "data_analyst",
            ),
            (
                "Kiểm tra mục tiêu goal hiện tại của tôi trên hệ thống",
                "backend_action",
                "backend_executor",
            ),
            (
                "Xin chào, bạn là ai?",
                "general_chat",
                "FINISH",
            ),
        ]
        for query, expected_intent, expected_next in cases:
            decision = await self.router.route(
                {"messages": [HumanMessage(content=query)], "iteration_count": 0}
            )
            self.assertEqual(decision.intent, expected_intent, msg=f"Failed query: {query}")
            self.assertEqual(decision.next_agent, expected_next, msg=f"Failed query: {query}")

    async def test_end_to_end_workflow_data_analyst_route(self):
        result = await self.workflow.ainvoke(
            {
                "messages": [
                    HumanMessage(content="Tính BMI và TDEE cho nam 70kg, 175cm, 25 tuổi")
                ],
                "session_id": "eval-session-1",
                "iteration_count": 0,
                "tool_outputs": [],
                "context": {},
            },
            config={"configurable": {"thread_id": "eval-session-1"}},
        )
        self.assertEqual(len(result["tool_outputs"]), 1)
        self.assertEqual(result["tool_outputs"][0]["tool"], "calculate_health_metrics")
        last_msg = result["messages"][-1]
        self.assertIn("BMI", str(last_msg.content))
        self.assertIn("TDEE", str(last_msg.content))

    async def test_end_to_end_workflow_backend_executor_route(self):
        result = await self.workflow.ainvoke(
            {
                "messages": [HumanMessage(content="Xem mục tiêu hiện tại của tôi")],
                "session_id": "eval-session-2",
                "iteration_count": 0,
                "tool_outputs": [],
                "context": {},
            },
            config={"configurable": {"thread_id": "eval-session-2"}},
        )
        self.assertEqual(len(result["tool_outputs"]), 1)
        self.assertEqual(result["tool_outputs"][0]["tool"], "get_current_goal")
        self.assertIn("Tăng cơ lên 75kg", str(result["messages"][-1].content))

    async def test_fastapi_chat_and_health_endpoints(self):
        app = create_agentic_app()
        app.state.workflow_graph = self.workflow
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://agentic-test"
        ) as client:
            health_resp = await client.get("/health")
            self.assertEqual(health_resp.status_code, 200)
            self.assertEqual(health_resp.json()["service"], "hercfit-agentic")

            chat_resp = await client.post(
                "/api/v1/chat",
                json={
                    "message": "Tính BMI cho 68kg, 172cm, 23 tuổi",
                    "session_id": "api-sess-1",
                },
            )
            self.assertEqual(chat_resp.status_code, 200)
            body = chat_resp.json()
            self.assertEqual(body["session_id"], "api-sess-1")
            self.assertEqual(body["agent_used"], "data_analyst_agent")
            self.assertIn("BMI", body["reply"])

            hist_resp = await client.get("/api/v1/chat/history/api-sess-1")
            self.assertEqual(hist_resp.status_code, 200)
            self.assertEqual(hist_resp.json()["message_count"], 2)


if __name__ == "__main__":
    unittest.main()
