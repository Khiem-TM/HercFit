"""Supervisor / Orchestrator Agent responsible for intent classification and routing."""

from typing import Any

from agents.base import BaseAgent
from core.llm import AIMessage, RunnableConfig
from core.state import AgentState, IntentType, RouteDecision

_DATA_ANALYST_KEYWORDS = (
    "bmi",
    "bmr",
    "tdee",
    "macro",
    "calo",
    "calories",
    "tính",
    "calculate",
    "phân tích",
    "protein",
    "thâm hụt",
    "deficit",
    "+",
    "-",
    "*",
    "/",
)

_BACKEND_EXECUTOR_KEYWORDS = (
    "hồ sơ",
    "profile",
    "mục tiêu",
    "goal",
    "cân nặng hiện tại",
    "chỉ số cơ thể",
    "body metric",
    "ghi nhận",
    "log",
    "tiến độ",
    "progress",
    "món ăn",
    "thực phẩm",
    "food",
    "bài tập",
    "exercise",
)


class RouterAgent(BaseAgent):
    """Supervisor / Orchestrator classifying user intent and routing to specialist agents."""

    name = "router_agent"
    description = "Supervisor classifying user intent and routing between DataAnalystAgent and BackendExecutorAgent."
    default_system_prompt = (
        "Bạn là Router Agent (Supervisor) của HercFit. "
        "Phân loại yêu cầu vào data_analysis, backend_action hoặc general_chat."
    )

    def classify_intent_heuristic(self, user_text: str) -> RouteDecision:
        """Deterministic intent classification fallback & fast-path for clear intents."""
        lowered = user_text.lower().strip()

        if any(kw in lowered for kw in _BACKEND_EXECUTOR_KEYWORDS):
            return RouteDecision(
                intent="backend_action",
                next_agent="backend_executor",
                reasoning="Detected request for user profile, goals, body metrics, progress, or catalog lookup.",
            )

        if any(kw in lowered for kw in _DATA_ANALYST_KEYWORDS):
            return RouteDecision(
                intent="data_analysis",
                next_agent="data_analyst",
                reasoning="Detected request for health metric calculation, math, or nutrition/fitness analysis.",
            )

        return RouteDecision(
            intent="general_chat",
            next_agent="FINISH",
            reasoning="General conversation or greeting handled directly by Supervisor.",
            direct_reply=(
                "Xin chào! Tôi là trợ lý AI của HercFit. Tôi có thể giúp bạn tính BMI/BMR/TDEE, "
                "tra cứu thực phẩm/bài tập, hoặc kiểm tra mục tiêu và tiến độ tập luyện của bạn."
            ),
        )

    async def route(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> RouteDecision:
        """Determine the next node in the workflow."""
        iteration = int(state.get("iteration_count") or 0)
        # If a specialist agent has already run and produced an answer in this turn, finish.
        if iteration > 0 and state.get("next_agent") in {
            "FINISH",
            "data_analyst",
            "backend_executor",
        }:
            return RouteDecision(
                intent="finish",
                next_agent="FINISH",
                reasoning="Specialist agent completed execution for the current turn.",
            )

        user_text = self.latest_user_text(state)
        if self.is_fake_model():
            return self.classify_intent_heuristic(user_text)

        model = self.get_model()
        if hasattr(model, "with_structured_output"):
            try:
                structured_llm = model.with_structured_output(RouteDecision)
                decision = await structured_llm.ainvoke(
                    self.build_messages(state), config=config
                )
                if isinstance(decision, RouteDecision):
                    return decision
            except Exception:
                pass

        return self.classify_intent_heuristic(user_text)

    async def ainvoke(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        decision = await self.route(state, config=config)
        updates: dict[str, Any] = {
            "intent": decision.intent,
            "next_agent": decision.next_agent,
            "reasoning": decision.reasoning,
            "iteration_count": int(state.get("iteration_count") or 0) + 1,
        }
        if decision.next_agent == "FINISH" and decision.direct_reply:
            updates["messages"] = [AIMessage(content=decision.direct_reply, name=self.name)]
        return updates
