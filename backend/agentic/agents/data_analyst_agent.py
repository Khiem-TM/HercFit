"""Specialized Agent for data analysis, health calculations (BMI/BMR/TDEE/Macros), and logic processing."""

import re
from typing import Any

from agents.base import BaseAgent
from core.llm import AIMessage, RunnableConfig
from core.state import AgentState
from tools import (
    SYSTEM_TOOLS,
    compute_health_metrics,
    evaluate_math,
    search_fitness_knowledge,
)


class DataAnalystAgent(BaseAgent):
    """Agent specialized in quantitative health metrics, nutrition calculations, and analytical logic."""

    name = "data_analyst_agent"
    description = "Calculates BMI, BMR, TDEE, macros, mathematical formulas, and fitness science analysis."
    default_system_prompt = (
        "Bạn là Data Analyst Agent của HercFit, chuyên tính toán BMI, BMR, TDEE, Macro và phân tích dữ liệu tập luyện."
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("tools", list(SYSTEM_TOOLS))
        super().__init__(**kwargs)

    @staticmethod
    def _extract_body_numbers(text: str) -> dict[str, Any]:
        weight_match = re.search(r"(\d+(?:\.\d+)?)\s*kg", text, re.IGNORECASE)
        height_match = re.search(r"(\d+(?:\.\d+)?)\s*cm", text, re.IGNORECASE)
        age_match = re.search(r"(\d{1,3})\s*(?:tuổi|age|yo)", text, re.IGNORECASE)

        weight_kg = float(weight_match.group(1)) if weight_match else 70.0
        height_cm = float(height_match.group(1)) if height_match else 170.0
        age = int(age_match.group(1)) if age_match else 25
        gender = "female" if any(w in text.lower() for w in ("nữ", "female")) else "male"
        goal_type = "maintain"
        if any(w in text.lower() for w in ("giảm cân", "giảm mỡ", "lose", "cut")):
            goal_type = "lose_weight"
        elif any(w in text.lower() for w in ("tăng cơ", "tăng cân", "gain", "bulk")):
            goal_type = "gain_muscle"

        return {
            "weight_kg": weight_kg,
            "height_cm": height_cm,
            "age": age,
            "gender": gender,
            "goal_type": goal_type,
        }

    async def ainvoke(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        user_text = self.latest_user_text(state)
        tool_outputs = list(state.get("tool_outputs") or [])
        context = dict(state.get("context") or {})

        lowered = user_text.lower()
        math_match = re.search(r"(\d+(?:\.\d+)?\s*[\+\-\*\/]\s*\d+(?:\.\d+)?(?:\s*[\+\-\*\/]\s*\d+(?:\.\d+)?)?)", lowered)

        if any(k in lowered for k in ("bmi", "bmr", "tdee", "macro", "calo", "kg", "cm")):
            params = self._extract_body_numbers(user_text)
            metrics = compute_health_metrics(**params)
            tool_outputs.append({"tool": "calculate_health_metrics", "output": metrics})
            context["health_metrics"] = metrics
            summary = (
                f"Kết quả phân tích chỉ số cơ thể ({params['weight_kg']}kg, {params['height_cm']}cm, {params['age']} tuổi):\n"
                f"- BMI: {metrics['bmi']} ({metrics['bmi_category']})\n"
                f"- BMR: {metrics['bmr_kcal']} kcal/ngày\n"
                f"- TDEE: {metrics['tdee_kcal']} kcal/ngày\n"
                f"- Calo mục tiêu: {metrics['target_calories_kcal']} kcal/ngày "
                f"(Protein: {metrics['macros_g']['protein_g']}g, Carbs: {metrics['macros_g']['carbs_g']}g, Fat: {metrics['macros_g']['fat_g']}g)"
            )
        elif math_match:
            expr = math_match.group(1)
            calc_res = evaluate_math(expression=expr)
            tool_outputs.append({"tool": "evaluate_math_expression", "output": calc_res})
            summary = f"Kết quả tính toán biểu thức `{calc_res['expression']}` là: {calc_res['result']}."
        else:
            articles = search_fitness_knowledge(query=user_text or "protein")
            tool_outputs.append({"tool": "search_knowledge_base", "output": articles})
            top = articles[0]
            summary = f"**{top['title']}**: {top['content']}"

        if not self.is_fake_model():
            model = self.get_model()
            response = await model.ainvoke(
                [
                    *self.build_messages(state),
                    AIMessage(content=f"[Tool Context]\n{summary}"),
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
            "next_agent": "FINISH",
        }
