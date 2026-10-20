"""Unit tests for tool logic, decorators, Pydantic schemas, config loading, and memory."""

import unittest

from pydantic import ValidationError

from config.settings import agent_settings, load_agent_yaml_config
from core.exceptions import ToolCallError
from memory.long_term import LongTermMemory
from memory.short_term import ShortTermMemory
from schemas.request import ChatRequest
from tools.decorators import tool_monitor
from tools.definitions.system_tools import (
    compute_health_metrics,
    evaluate_math,
    search_fitness_knowledge,
)
from tools.schemas.user_schemas import BodyMetricLogInput, HealthMetricsCalcInput


class UnitToolsAndSchemasTests(unittest.IsolatedAsyncioTestCase):
    def test_yaml_config_and_settings_loaded(self):
        cfg = load_agent_yaml_config()
        self.assertIn("agents", cfg)
        self.assertIn("router_agent", cfg["agents"])
        self.assertIn("data_analyst_agent", cfg["agents"])
        self.assertIn("backend_executor_agent", cfg["agents"])
        self.assertTrue(agent_settings.BACKEND_BASE_URL.startswith("http"))

    def test_health_metrics_calculation_and_validation(self):
        result = compute_health_metrics(
            weight_kg=72.0,
            height_cm=175.0,
            age=25,
            gender="male",
            activity_level="moderate",
            goal_type="lose_weight",
        )
        self.assertAlmostEqual(result["bmi"], 23.51, places=2)
        self.assertEqual(result["bmi_category"], "normal")
        self.assertGreater(result["tdee_kcal"], result["bmr_kcal"])
        self.assertLess(result["target_calories_kcal"], result["tdee_kcal"])
        self.assertIn("protein_g", result["macros_g"])

        with self.assertRaises(ValidationError):
            HealthMetricsCalcInput(weight_kg=-5, height_cm=170, age=25)

        with self.assertRaises(ValidationError):
            BodyMetricLogInput(weight_kg=500)

    def test_safe_math_evaluator(self):
        res = evaluate_math(expression="(70 * 2.2) + 100 / 4")
        self.assertAlmostEqual(res["result"], 179.0, places=2)

        with self.assertRaises(ToolCallError):
            evaluate_math(expression="__import__('os').system('ls')")

    def test_knowledge_search(self):
        articles = search_fitness_knowledge(query="protein")
        self.assertGreaterEqual(len(articles), 1)
        self.assertEqual(articles[0]["topic"], "protein")

    async def test_tool_monitor_retries_and_wraps_exception(self):
        attempts = 0

        @tool_monitor(name="flaky_tool", max_retries=3, retry_delay=0.01)
        async def flaky_func(x: int, auth_token: str | None = None) -> int:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary failure")
            return x * 2

        val = await flaky_func(x=21, auth_token="secret-jwt")
        self.assertEqual(val, 42)
        self.assertEqual(attempts, 3)

        @tool_monitor(name="always_failing_tool", max_retries=2, retry_delay=0.01)
        async def failing_func(auth_token: str = "secret") -> None:
            raise ValueError("bad input")

        with self.assertRaises(ToolCallError) as ctx:
            await failing_func(auth_token="super-secret-token")
        self.assertEqual(ctx.exception.tool_name, "always_failing_tool")
        self.assertEqual(ctx.exception.payload["auth_token"], "***REDACTED***")

    async def test_short_and_long_term_memory(self):
        stm = ShortTermMemory(max_messages=3)
        for i in range(5):
            stm.append_user_text("sess-1", f"msg-{i}")
        msgs = stm.get_session_messages("sess-1")
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0].content, "msg-2")

        ltm = LongTermMemory()
        await ltm.store_fact("user-1", "Dị ứng hải sản và thích tập buổi sáng")
        hits = await ltm.retrieve_relevant("user-1", "hải sản")
        self.assertEqual(len(hits), 1)
        self.assertIn("hải sản", hits[0]["content"])

    def test_chat_request_schema(self):
        req = ChatRequest(message="Xin chào HercFit")
        self.assertTrue(req.session_id)
        with self.assertRaises(ValidationError):
            ChatRequest(message="")


if __name__ == "__main__":
    unittest.main()

