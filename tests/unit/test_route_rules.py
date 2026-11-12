"""Luật code sau router (agentic/services/route_rules.py): mỗi luật một bảng ca đầu vào → đầu ra, và thứ tự POST_ROUTER."""
import pytest

from agentic.agents.state import RouteDecision
from agentic.services import mode
from agentic.services import route_rules as rules
from agentic.services.route_rules import POST_ROUTER, Applied, RouteContext, run

CARD = {"body": {"weight_kg": 70, "height_cm": 175}, "profile": {"age": 28}}
TWO_TASKS = [{"domain": "meals", "intent": "LOG_FOOD", "instruction": "Ghi bữa sáng."},
             {"domain": "trainings", "intent": "LOG_EXERCISE", "instruction": "Ghi buổi chạy."}]
MEAL = [{"name": "Bữa sáng", "items": [{"food": "bánh bao", "quantity": 1, "unit": "SERVING"}]}]


def route(intent="GENERAL_CHAT", action="answer", domain=None, **extra):
    agent = extra.pop("next_agent", {"tool": "tool", "research": "research"}.get(action, "orchestrator"))
    return RouteDecision(intent=intent, action=action, next_agent=agent, domain=domain, instruction="x", **extra)


def context(chat=mode.FULL, request="", **extra):
    values = {"state": {}, "card": None, "read_policy": {}, "first": True, "verdict": None, "parallel": True,
              **extra}
    return RouteContext(policy=mode.POLICIES[chat], request=request, **values)


# (luật, quyết định, ngữ cảnh, tên luật trong vết | None khi luật không có tác dụng, các trường quyết định sau luật)
CASES = [
    (rules.primary_task_domain, route("LOG_FOOD", "tool", tasks=TWO_TASKS[:1]), context(),
     "primary_task_domain", {"domain": "meals"}),
    (rules.primary_task_domain, route("LOG_FOOD", "tool", "trainings", tasks=TWO_TASKS[:1]), context(), None, {}),
    (rules.primary_task_domain, route(tasks=TWO_TASKS[:1]), context(), None, {}),
    (rules.read_only_policy, route("READ", "research"), context(read_policy={"read_only": True, "domain": "metrics"}),
     "", {"action": "answer", "domain": "metrics", "read_only": True}),
    (rules.read_only_policy, route("READ", "tool", "metrics"),
     context(read_policy={"read_only": True, "domain": "metrics"}), "", {"action": "tool", "read_only": True}),
    (rules.read_only_policy, route("READ", "research"), context(), None, {}),
    (rules.clarify_to_catalog_lookup, route("LOG_EXERCISE", "clarify", "trainings", missing_fields=["exercise_id"]),
     context(), "clarify_to_catalog_lookup", {"action": "tool", "next_agent": "tool"}),
    (rules.clarify_to_catalog_lookup, route("LOG_EXERCISE", "clarify", "trainings", missing_fields=["thời lượng"]),
     context(), None, {}),
    (rules.clarify_known_facts, route("BMR", "clarify", "profile", missing_fields=["cân nặng"]), context(card=CARD),
     "clarify_known_facts", {"action": "answer", "missing_fields": []}),
    (rules.clarify_known_facts, route("BMR", "clarify", "profile", missing_fields=["cân nặng"]), context(), None, {}),
    (rules.clarify_known_facts, route("BMR", "clarify", "profile", missing_fields=["cân nặng"]),
     context(card={"body": {}}), None, {}),
    (rules.personalization, route(), context(request="Tôi có nên nghỉ thêm một ngày không"),
     "personalize", {"personalize": True, "topic": "general", "action": "answer"}),
    (rules.personalization, route(research_query="chạy 5K dưới 25 phút"),
     context(mode.PLAN, "Làm sao để tôi chạy 5K dưới 25 phút"),
     "plan_deep", {"personalize": True, "topic": "running", "action": "research"}),
    (rules.personalization, route(topic="body"), context(request="Cảm ơn bạn"),
     "", {"personalize": False, "topic": None}),
    (rules.personalization, route(personalize=True), context(request="Cảm ơn bạn"), "personalize",
     {"personalize": True}),
    (rules.personalization, route("LOG_FOOD", "tool", "meals"), context(mode.PLAN, "Sáng nay tôi ăn 1 bánh bao"),
     "", {"personalize": False}),
    (rules.personalization, route(plan_task="plan_build"), context(request="Cảm ơn bạn"), "", {"plan_task": None}),
    (rules.chat_to_knowledge, route(research_query="tác dụng creatine"), context(request="Creatine có tác dụng gì"),
     "chat_to_knowledge", {"intent": "SPORTS_KNOWLEDGE_QA"}),
    (rules.chat_to_knowledge, route(research_query="tác dụng creatine"),
     context(request="Creatine có tác dụng gì", first=False), None, {}),
    (rules.chat_to_knowledge, route(), context(request="Hôm nay trời đẹp quá"), None, {}),
    (rules.training_read_first, route("TRAINING_REVIEW", "clarify", "trainings"), context(),
     "training_read_first", {"action": "tool"}),
    (rules.training_read_first, route("TRAINING_REVIEW", "research", "trainings"), context(),
     "training_read_first", {"action": "tool"}),
    (rules.training_read_first, route("TRAINING_REVIEW", "clarify", "trainings", missing_fields=["khoảng ngày"]),
     context(), None, {}),
    (rules.plan_catalog_only, route("TRAINING_PLAN", "research", "exercises"), context(),
     "plan_catalog_only", {"domain": "training_plans", "action": "tool"}),
    (rules.plan_catalog_only, route("TRAINING_PLAN", "tool", "training_plans"), context(), None, {}),
    (rules.tool_next_agent, route("LOG_FOOD", "tool", "meals", next_agent="orchestrator"), context(),
     "tool_next_agent", {"next_agent": "tool"}),
    (rules.tool_next_agent, route("LOG_FOOD", "tool", "meals"), context(), None, {}),
    (rules.require_tool_domain, route("LOG_FOOD", "tool", "meals"), context(), None, {}),
    (rules.knowledge_to_research, route("SPORTS_KNOWLEDGE_QA", "research"), context(), "", {"action": "research"}),
    (rules.knowledge_to_research, route("SPORTS_KNOWLEDGE_QA", "tool", "training_plans"), context(), None, {}),
    (rules.knowledge_to_research, route("SPORTS_KNOWLEDGE_QA", personalize=True), context(), None, {}),
    (rules.catalog_research, route("FOOD_LOOKUP", "research", "meals", research_query="bánh bao", meal_log=MEAL),
     context(), "food_research_to_catalog", {"action": "tool", "domain": "meals", "intent": "LOG_FOOD"}),
    (rules.catalog_research, route("LOOKUP", "research", "trainings", research_query="split squat"), context(),
     "", {"domain": "exercises", "action": "research"}),
    (rules.catalog_research, route("SPORTS_KNOWLEDGE_QA", "research"), context(), None, {}),
    (rules.read_only_recheck, route("LOG_EXERCISE", "tool", "trainings"),
     context(read_policy={"read_only": True, "domain": "metrics"}), "", {"action": "answer", "domain": "metrics"}),
    (rules.read_only_recheck, route("READ", "tool", "metrics"),
     context(read_policy={"read_only": True, "domain": "metrics"}), None, {}),
    (rules.food_suggestion_lookup, route(), context(request="Gợi ý món ăn sáng"), "",
     {"intent": "FOOD_SUGGESTION", "action": "tool", "domain": "foods", "read_only": True}),
    (rules.food_suggestion_lookup, route(personalize=True), context(request="Gợi ý món ăn sáng"), None, {}),
    (rules.food_suggestion_lookup, route(), context(request="Gợi ý món ăn sáng", state={"tool_outputs": [
        {"tool": "list_foods", "ok": True}]}), None, {}),
    (rules.food_suggestion_lookup, route(), context(request="Gợi ý món ăn sáng",
                                                    read_policy={"read_only": True, "domain": "metrics"}), None, {}),
    (rules.plan_mode_only, route("SPORTS_KNOWLEDGE_QA", "research"), context(mode.NORMAL), "plan_mode_only",
     {"action": "answer", "personalize": False}),
    (rules.plan_mode_only, route("SLEEP_REVIEW", "tool", "health"), context(mode.NORMAL), "plan_mode_only",
     {"action": "answer"}),
    (rules.plan_mode_only, route("SPORTS_KNOWLEDGE_QA", "research"), context(), None, {}),
    (rules.plan_mode_only, route("LOG_FOOD", "tool", "meals"), context(mode.NORMAL), None, {}),
    (rules.owner_preflight, route("LOG_EXERCISE", "tool", "trainings"), context(request="Hôm nay tôi tập gym"),
     "gym_mode_guard", {"action": "clarify", "missing_fields": ["gym_logging_mode"]}),
    (rules.owner_preflight, route("LOG_EXERCISE", "tool", "trainings"), context(request="Tập gym squat 3x5 60kg"),
     None, {}),
    (rules.owner_preflight, route("LOG_FOOD", "tool", "meals"), context(request="Hôm nay tôi tập gym"), None, {}),
    (rules.fan_out, route("LOG_FOOD", "tool", "meals", tasks=TWO_TASKS), context(parallel=False), None, {}),
    (rules.fan_out, route("LOG_FOOD", "tool", "meals", tasks=TWO_TASKS), context(first=False), None, {}),
    (rules.fan_out, route("LOG_FOOD", "tool", "meals", tasks=TWO_TASKS), context(outputs={"redirect": True}),
     None, {}),
    (rules.fan_out, route("LOG_FOOD", "tool", "meals", tasks=TWO_TASKS[:1]), context(), None, {}),
]


@pytest.mark.parametrize(("rule", "decision", "ctx", "name", "fields"), CASES,
                         ids=[f"{case[0].__name__}-{i}" for i, case in enumerate(CASES)])
def test_rule(rule, decision, ctx, name, fields):
    applied = rule(decision, ctx)
    if name is None:
        assert applied is None
        return
    assert isinstance(applied, Applied)
    label = applied.trace["rule"] if isinstance(applied.trace, dict) else applied.trace
    assert (label or "") == name
    for key, value in fields.items():
        assert getattr(applied.decision, key) == value, key


def test_knowledge_to_research_traces_the_action_before_the_change():
    applied = rules.knowledge_to_research(route("SPORTS_KNOWLEDGE_QA", "answer"), context())
    assert applied.trace == {"stage": "rule", "rule": "knowledge_to_research", "action": "answer", "domain": None}
    assert (applied.decision.action, applied.decision.next_agent) == ("research", "research")


def test_food_gap_card_asks_with_a_card():
    applied = rules.catalog_research(route("FOOD_LOOKUP", "research", "foods", research_query="bánh xèo"), context())
    assert applied.trace == "food_gap_card"
    assert applied.decision.action == "answer"
    assert applied.outputs["gap"]["food_gap"]["items"][0]["query"] == "bánh xèo"


def test_catalog_research_outside_catalog_domains_is_refused():
    with pytest.raises(ValueError):
        rules.catalog_research(route("LOOKUP", "research", "metrics"), context())


def test_tool_route_without_domain_is_refused():
    with pytest.raises(ValueError):
        rules.require_tool_domain(route("LOG_FOOD", "tool"), context())


def test_gym_guard_returns_its_form():
    applied = rules.owner_preflight(route("LOG_EXERCISE", "tool", "trainings"), context(request="Hôm nay tôi tập gym"))
    form, reply = applied.outputs["form"]
    assert form["questions"][0]["mode"] == "single" and reply


def test_fan_out_delegates_one_task_per_agent():
    applied = rules.fan_out(route("LOG_FOOD", "tool", "meals", tasks=TWO_TASKS, meal_log=MEAL), context())
    assert applied.trace == {"stage": "rule", "rule": "fan_out", "action": "delegate", "domain": None,
                             "agents": ["nutrition", "training_log"]}
    tasks = applied.outputs["delegated"]
    assert [task["domain"] for task in tasks] == ["meals", "trainings"]
    assert tasks[0]["meal_log"][0]["items"][0]["food"] == "bánh bao"


def test_post_router_order():
    assert [rule.__name__ for rule in POST_ROUTER] == [
        "primary_task_domain", "read_only_policy", "clarify_to_catalog_lookup", "clarify_known_facts",
        "personalization", "chat_to_knowledge", "training_read_first", "plan_catalog_only", "tool_next_agent",
        "require_tool_domain", "knowledge_to_research", "catalog_research", "read_only_recheck",
        "food_suggestion_lookup", "plan_mode_only", "owner_preflight", "fan_out",
    ]


def test_run_traces_each_rule_and_shares_outputs():
    seen = []

    def first(decision, ctx):
        decision.domain = "meals"
        return Applied(decision, "first", {"redirect": True})

    def silent(decision, ctx):
        seen.append(dict(ctx.outputs))
        return Applied(decision)

    def custom(decision, ctx):
        return Applied(decision, {"stage": "rule", "rule": "custom", "action": "delegate", "domain": None})

    decision, trace, outputs = run((first, silent, lambda d, c: None, custom), route("LOG_FOOD", "tool"), context())
    assert decision.domain == "meals"
    assert trace == [{"stage": "rule", "rule": "first", "action": "tool", "domain": "meals"},
                     {"stage": "rule", "rule": "custom", "action": "delegate", "domain": None}]
    assert outputs == {"redirect": True} and seen == [{"redirect": True}]
