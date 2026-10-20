"""Specialized Agent responsible for invoking HercFit CRUD Backend business APIs."""

import re
from typing import Any

from agents.base import BaseAgent
from clients.backend_client import BackendClient
from core.exceptions import BackendAPIError, ToolCallError
from core.llm import AIMessage, RunnableConfig
from core.state import AgentState
from tools import (
    BACKEND_TOOLS,
    fetch_current_goal,
    fetch_latest_body_metrics,
    fetch_progress_overview,
    fetch_user_profile,
    record_body_metric,
    search_backend_exercises,
    search_backend_foods,
)


class BackendExecutorAgent(BaseAgent):
    """Agent specialized in executing CRUD Backend API calls via backend_tools."""

    name = "backend_executor_agent"
    description = "Interacts with HercFit Backend APIs for profile, goals, body metrics, progress, foods, and exercises."
    default_system_prompt = (
        "Bạn là Backend Executor Agent của HercFit, chuyên truy vấn và cập nhật dữ liệu nghiệp vụ qua Backend API."
    )

    def __init__(
        self,
        *,
        backend_client: BackendClient | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("tools", list(BACKEND_TOOLS))
        super().__init__(**kwargs)
        self.backend_client = backend_client

    async def _execute_backend_action(
        self, user_text: str, auth_token: str | None
    ) -> tuple[str, dict[str, Any]]:
        lowered = user_text.lower()

        if any(k in lowered for k in ("ghi nhận", "cập nhật cân nặng", "log")):
            weight_match = re.search(r"(\d+(?:\.\d+)?)\s*kg", user_text, re.IGNORECASE)
            weight_kg = float(weight_match.group(1)) if weight_match else 70.0
            result = await record_body_metric(
                weight_kg=weight_kg,
                auth_token=auth_token,
                client=self.backend_client,
            )
            return "log_body_metrics", result

        if any(k in lowered for k in ("mục tiêu", "goal")):
            result = await fetch_current_goal(
                auth_token=auth_token, client=self.backend_client
            )
            return "get_current_goal", result

        if any(k in lowered for k in ("chỉ số cơ thể", "body metric", "cân nặng hiện tại")):
            result = await fetch_latest_body_metrics(
                auth_token=auth_token, client=self.backend_client
            )
            return "get_latest_body_metrics", result

        if any(k in lowered for k in ("tiến độ", "progress")):
            result = await fetch_progress_overview(
                auth_token=auth_token, client=self.backend_client
            )
            return "get_progress_overview", result

        if any(k in lowered for k in ("món ăn", "thực phẩm", "food")):
            keyword = re.sub(
                r"(tìm|tra cứu|món ăn|thực phẩm|food|cho tôi|về)",
                "",
                lowered,
            ).strip() or "ức gà"
            items = await search_backend_foods(
                search=keyword,
                limit=5,
                auth_token=auth_token,
                client=self.backend_client,
            )
            return "search_foods", {"items": items, "keyword": keyword}

        if any(k in lowered for k in ("bài tập", "exercise")):
            keyword = re.sub(
                r"(tìm|tra cứu|bài tập|exercise|cho tôi|về)",
                "",
                lowered,
            ).strip() or "squat"
            items = await search_backend_exercises(
                search=keyword,
                limit=5,
                auth_token=auth_token,
                client=self.backend_client,
            )
            return "search_exercises", {"items": items, "keyword": keyword}

        result = await fetch_user_profile(
            auth_token=auth_token, client=self.backend_client
        )
        return "get_user_profile", result

    async def ainvoke(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        user_text = self.latest_user_text(state)
        auth_token = state.get("auth_token")
        tool_outputs = list(state.get("tool_outputs") or [])
        context = dict(state.get("context") or {})
        error_msg: str | None = None

        try:
            tool_name, data = await self._execute_backend_action(user_text, auth_token)
            tool_outputs.append({"tool": tool_name, "output": data})
            context["last_backend_result"] = data
            summary = f"Đã thực thi `{tool_name}` thành công từ HercFit Backend: {data}"
        except (ToolCallError, BackendAPIError) as exc:
            error_msg = exc.message
            tool_outputs.append({"tool": "backend_error", "error": exc.message})
            summary = f"Không thể hoàn tất truy vấn Backend: {exc.message}"

        if not self.is_fake_model() and error_msg is None:
            model = self.get_model()
            response = await model.ainvoke(
                [
                    *self.build_messages(state),
                    AIMessage(content=f"[Backend Tool Output]\n{summary}"),
                ],
                config=config,
            )
            reply_text = str(response.content) or summary
        else:
            reply_text = summary

        return {
            "messages": [AIMessage(content=reply_text, name=self.name)],
            "tool_outputs": tool_outputs,
            "context": context,
            "error": error_msg,
            "next_agent": "FINISH",
        }
