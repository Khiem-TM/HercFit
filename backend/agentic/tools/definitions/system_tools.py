"""System and analytical tools: health calculator, safe math evaluator, and knowledge search."""

import ast
import operator
from typing import Any, Literal

from core.llm import tool

from tools.decorators import tool_monitor
from tools.schemas.user_schemas import (
    HealthMetricsCalcInput,
    HealthMetricsCalcOutput,
    KnowledgeSearchInput,
    MathExpressionInput,
)

_ACTIVITY_MULTIPLIERS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

_ALLOWED_OPERATORS: dict[type[ast.AST], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_FITNESS_KNOWLEDGE_BASE: list[dict[str, str]] = [
    {
        "topic": "protein",
        "title": "Nhu cầu Protein cho người tập luyện",
        "content": "Người tập kháng lực (tăng cơ / giữ cơ khi giảm mỡ) nên nạp 1.6g - 2.2g protein trên mỗi kg trọng lượng cơ thể mỗi ngày.",
    },
    {
        "topic": "caloric_deficit",
        "title": "Thâm hụt calo an toàn (Giảm mỡ)",
        "content": "Mức thâm hụt 300 - 500 kcal/ngày dưới TDEE giúp giảm khoảng 0.3 - 0.5 kg mỡ/tuần mà vẫn bảo toàn khối lượng cơ bắp.",
    },
    {
        "topic": "progressive_overload",
        "title": "Nguyên lý tăng tiến tải trọng (Progressive Overload)",
        "content": "Để phát triển cơ bắp và sức mạnh, cần tăng dần khối lượng tạ, số lần lặp (reps), số hiệp (sets) hoặc kiểm soát tempo qua từng tuần.",
    },
    {
        "topic": "hydration_sleep",
        "title": "Giấc ngủ và bù nước",
        "content": "Ngủ đủ 7-9 tiếng/đêm và uống khoảng 35-45ml nước/kg cân nặng mỗi ngày để tối ưu phục hồi thần kinh - cơ bắp.",
    },
]


def _classify_bmi(bmi: float) -> str:
    if bmi < 18.5:
        return "underweight"
    if bmi < 25.0:
        return "normal"
    if bmi < 30.0:
        return "overweight"
    return "obese"


@tool_monitor(name="calculate_health_metrics", max_retries=1)
def compute_health_metrics(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: Literal["male", "female"] = "male",
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] = "moderate",
    goal_type: Literal["lose_weight", "maintain", "gain_muscle"] = "maintain",
) -> dict[str, Any]:
    """Calculate BMI, BMR (Mifflin-St Jeor), TDEE, and daily macro targets."""
    validated = HealthMetricsCalcInput(
        weight_kg=weight_kg,
        height_cm=height_cm,
        age=age,
        gender=gender,
        activity_level=activity_level,
        goal_type=goal_type,
    )
    height_m = validated.height_cm / 100.0
    bmi = round(validated.weight_kg / (height_m**2), 2)
    bmi_category = _classify_bmi(bmi)

    sex_offset = 5.0 if validated.gender == "male" else -161.0
    bmr = round(
        (10.0 * validated.weight_kg)
        + (6.25 * validated.height_cm)
        - (5.0 * validated.age)
        + sex_offset,
        1,
    )
    multiplier = _ACTIVITY_MULTIPLIERS[validated.activity_level]
    tdee = round(bmr * multiplier, 1)

    if validated.goal_type == "lose_weight":
        target_calories = max(1200.0, round(tdee - 450.0, 1))
        protein_g = round(validated.weight_kg * 2.0, 1)
        fat_g = round(validated.weight_kg * 0.8, 1)
    elif validated.goal_type == "gain_muscle":
        target_calories = round(tdee + 300.0, 1)
        protein_g = round(validated.weight_kg * 1.8, 1)
        fat_g = round(validated.weight_kg * 0.9, 1)
    else:
        target_calories = tdee
        protein_g = round(validated.weight_kg * 1.6, 1)
        fat_g = round(validated.weight_kg * 0.85, 1)

    remaining_kcal = max(0.0, target_calories - (protein_g * 4.0 + fat_g * 9.0))
    carbs_g = round(remaining_kcal / 4.0, 1)

    output = HealthMetricsCalcOutput(
        bmi=bmi,
        bmi_category=bmi_category,
        bmr_kcal=bmr,
        tdee_kcal=tdee,
        target_calories_kcal=target_calories,
        macros_g={"protein_g": protein_g, "carbs_g": carbs_g, "fat_g": fat_g},
    )
    return output.model_dump()


def _eval_ast_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        left = _eval_ast_node(node.left)
        right = _eval_ast_node(node.right)
        return float(_ALLOWED_OPERATORS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        operand = _eval_ast_node(node.operand)
        return float(_ALLOWED_OPERATORS[type(node.op)](operand))
    raise ValueError(f"Unsupported syntax in arithmetic expression: {ast.dump(node)}")


@tool_monitor(name="evaluate_math_expression", max_retries=1)
def evaluate_math(expression: str) -> dict[str, Any]:
    """Safely evaluate an arithmetic math expression using Python AST."""
    validated = MathExpressionInput(expression=expression)
    parsed = ast.parse(validated.expression, mode="eval")
    value = round(_eval_ast_node(parsed.body), 4)
    return {"expression": validated.expression, "result": value}


@tool_monitor(name="search_knowledge_base", max_retries=1)
def search_fitness_knowledge(query: str) -> list[dict[str, str]]:
    """Search built-in fitness and nutrition knowledge articles."""
    validated = KnowledgeSearchInput(query=query)
    q_lower = validated.query.lower()
    matches = [
        item
        for item in _FITNESS_KNOWLEDGE_BASE
        if q_lower in item["topic"].lower()
        or q_lower in item["title"].lower()
        or q_lower in item["content"].lower()
    ]
    return matches if matches else _FITNESS_KNOWLEDGE_BASE[:2]


@tool("calculate_health_metrics", args_schema=HealthMetricsCalcInput)
def calculate_health_metrics_tool(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: Literal["male", "female"] = "male",
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] = "moderate",
    goal_type: Literal["lose_weight", "maintain", "gain_muscle"] = "maintain",
) -> dict[str, Any]:
    """Calculate BMI, BMR, TDEE, and daily macro recommendations for a user."""
    return compute_health_metrics(
        weight_kg=weight_kg,
        height_cm=height_cm,
        age=age,
        gender=gender,
        activity_level=activity_level,
        goal_type=goal_type,
    )


@tool("evaluate_math_expression", args_schema=MathExpressionInput)
def evaluate_math_expression_tool(expression: str) -> dict[str, Any]:
    """Evaluate a mathematical expression safely."""
    return evaluate_math(expression=expression)


@tool("search_knowledge_base", args_schema=KnowledgeSearchInput)
def search_knowledge_base_tool(query: str) -> list[dict[str, str]]:
    """Search fitness and nutrition science guidelines."""
    return search_fitness_knowledge(query=query)


SYSTEM_TOOLS = [
    calculate_health_metrics_tool,
    evaluate_math_expression_tool,
    search_knowledge_base_tool,
]
