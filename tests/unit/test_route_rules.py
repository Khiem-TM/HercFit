"""Luật code trước và sau router (agentic/services/route_rules.py): mỗi luật một bảng ca đầu vào → đầu ra, và thứ
tự của PRE_ROUTER, POST_ROUTER."""
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from agentic.agents.state import RouteDecision
from agentic.security.content_filter import assess
from agentic.services import mode
from agentic.services import route_rules as rules
from agentic.services.route_rules import (
    POST_ROUTER,
    PRE_ROUTER,
    Applied,
    Pre,
    PreContext,
    RouteContext,
    run,
    run_pre,
)
from agentic.services.routing import latest_request

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


# ---------------------------------------------------------------- luật trước router

SETTINGS = SimpleNamespace(FAST_READ_ENABLED=True, MAX_TOOL_CALLS=12)
WRITE = {"tool": "create_meals", "ok": True, "action_id": "a-1", "output": {"id": "m-1"}}


def turn_state(text="", **extra):
    return {"messages": [HumanMessage(content=text)], "run_id": "r-1", "tool_outputs": [], "status": "running",
            **extra}


def pre(state, chat=mode.NORMAL, verdict=None, first=True, carry=None):
    return PreContext(state=state, policy=mode.POLICIES[chat], settings=SETTINGS, request=latest_request(state),
                      verdict=verdict, first=first, carry=carry or {})


BLOCK = assess("Dạo này tôi không muốn sống nữa, ăn kiêng cũng chẳng để làm gì")
CAUTION = assess("Tôi đang mang thai 4 tháng, có nên giảm cân không?")
CHOICE = {"domain": "exercises", "query": "split squat", "choices": {"tạo mới": {"kind": "create_distinct"}}}
GAP = {"items": [{"key": "0:0", "query": "bánh mì chảo"}], "meal_log": MEAL}
PICK = [{"key": "0:0", "food_id": "f-1", "quantity": 150, "unit": "G"}]
PLAN_BUILD = {"intent": "TRAINING_PLAN", "action": "research", "domain": "training_plans", "plan_task": "plan_build"}

# (luật, state, ngữ cảnh, kỳ vọng): None = không áp dụng; {"carry": ...} = tiếp tục với cập nhật mang theo;
# ngược lại là các trường của kết quả kết thúc bước định tuyến (khoá "intent" so với decision["intent"]).
PRE_CASES = [
    (rules.fast_read, turn_state("Cân nặng của tôi"), None, {"intent": "READ", "turn": True, "plan": True}),
    (rules.fast_read, turn_state("Cân nặng của tôi"), {"chat": mode.PLAN}, None),
    (rules.fast_read, turn_state("Cân nặng của tôi"), {"verdict": CAUTION}, None),
    (rules.fast_read, turn_state("Giấc ngủ của tôi"), None, None),
    (rules.simple_write, turn_state("cân nặng 68,2 kg"), None, {"intent": "LOG_METRICS", "turn": True, "plan": False}),
    (rules.simple_write, turn_state("cân nặng 68,2 kg", food_choices=PICK), None, None),
    (rules.food_suggestion_shortcut, turn_state("Gợi ý món ăn sáng"), None, {"intent": "FOOD_SUGGESTION"}),
    (rules.food_suggestion_shortcut, turn_state("Gợi ý món ăn sáng"), {"first": False}, None),
    (rules.food_suggestion_shortcut, turn_state("Gợi ý món ăn sáng", pending_action={"action_id": "a"}), None, None),
    (rules.status_answer, turn_state(status="needs_input"), None, {"intent": "clarification"}),
    (rules.status_answer, turn_state(status="failed", error="lỗi"), None, {"intent": "error"}),
    (rules.status_answer, turn_state(), None, None),
    (rules.tool_budget, turn_state(tool_count=12), None, {"intent": "limit", "status": "failed"}),
    (rules.tool_budget, turn_state(tool_count=11), None, None),
    (rules.safety_block, turn_state(), {"verdict": BLOCK}, {"intent": "SAFETY", "safety": True}),
    (rules.safety_block, turn_state(), {"verdict": CAUTION}, None),
    (rules.catalog_choice_answer, turn_state("Tạo mới", catalog_choice=CHOICE), {"carry": {"safety": "s"}},
     {"intent": "catalog_research", "safety": True}),
    (rules.catalog_choice_answer, turn_state("Thôi", catalog_choice=CHOICE), None, {"carry": {"catalog_choice": None}}),
    (rules.catalog_choice_answer, turn_state("Tạo mới"), None, None),
    (rules.food_gap_resolved, turn_state("Bánh mì chảo", food_gap=GAP, food_choices=PICK), None,
     {"intent": "LOG_FOOD", "rule": "food_gap_resolved"}),
    (rules.food_gap_resolved, turn_state("Bỏ qua", food_gap=GAP, food_choices=[]), None,
     {"carry": {"food_gap": None, "food_choices": None}}),
    (rules.food_gap_resolved, turn_state(), None, None),
    (rules.read_only_handoff, turn_state(decision={"read_only": True, "domain": "foods"},
                                         catalog_handoff={"domain": "foods"}), None, {"intent": "READ"}),
    (rules.read_only_handoff, turn_state(decision={"domain": "meals"}, catalog_handoff={"domain": "foods"}), None, None),
    (rules.catalog_handoff, turn_state(catalog_handoff={"domain": "foods"}), None, {"intent": "catalog_lookup"}),
    (rules.catalog_handoff, turn_state(catalog_handoff={"domain": "metrics"}), None, None),
    (rules.research_handoff, turn_state(research_handoff={"domain": "exercises", "query": "split squat"}), None,
     {"intent": "catalog_research"}),
    (rules.research_handoff, turn_state(), None, None),
    (rules.specialist_resume, turn_state(decision=PLAN_BUILD, research_count=1), {"carry": {"safety": "s"}},
     {"intent": "TRAINING_PLAN", "rule": "plan_build_tool", "safety": True}),
    (rules.specialist_resume, turn_state(decision=PLAN_BUILD), None, None),
    (rules.write_done, turn_state(decision={"intent": "LOG_FOOD", "domain": "meals", "writes_before": 0},
                                  tool_outputs=[WRITE]), None, {"intent": "LOG_FOOD", "rule": "write_done"}),
    (rules.write_done, turn_state(decision={"intent": "LOG_FOOD", "domain": "meals"}, tool_outputs=[WRITE]), None,
     None),
]


@pytest.mark.parametrize(("rule", "state", "options", "expected"), PRE_CASES,
                         ids=[f"{case[0].__name__}-{i}" for i, case in enumerate(PRE_CASES)])
def test_pre_rule(rule, state, options, expected):
    out = rule(state, pre(state, **(options or {})))
    if expected is None:
        assert out is None
        return
    if "carry" in expected:
        assert out == Pre(carry=expected["carry"])
        return
    result = out.result
    assert result["decision"]["intent"] == expected["intent"]
    if "turn" in expected:
        assert result["turn"]["run_id"] == "r-1"
        assert (result["fast_read_plan"] is not None) is expected["plan"]
    if "rule" in expected:
        assert result["route_trace"][-1]["rule"] == expected["rule"]
    for key in ("status", "safety"):
        if key in expected:
            assert bool(result.get(key)) if expected[key] is True else result.get(key) == expected[key]


def test_run_pre_carries_updates_into_the_rule_that_ends_the_step():
    state = turn_state("Thôi", catalog_choice=CHOICE, food_gap=GAP, food_choices=[], decision=PLAN_BUILD,
                       research_count=1)
    result, carry = run_pre(PRE_ROUTER, state, pre(state, chat=mode.FULL, verdict=CAUTION,
                                                   carry={"safety": CAUTION.as_state()}))
    assert result["route_trace"][-1]["rule"] == "plan_build_tool"
    assert {k: result[k] for k in ("catalog_choice", "food_gap", "food_choices")} == dict.fromkeys(
        ("catalog_choice", "food_gap", "food_choices"))
    assert result["safety"] == CAUTION.as_state() and carry == {**dict.fromkeys(
        ("catalog_choice", "food_gap", "food_choices")), "safety": CAUTION.as_state()}


def test_run_pre_falls_through_to_the_router():
    state = turn_state("Hôm nay trời đẹp quá")
    assert run_pre(PRE_ROUTER, state, pre(state)) == (None, {})


def test_pre_router_order():
    assert [rule.__name__ for rule in PRE_ROUTER] == [
        "fast_read", "simple_write", "food_suggestion_shortcut", "status_answer", "tool_budget", "safety_block",
        "catalog_choice_answer", "food_gap_resolved", "read_only_handoff", "catalog_handoff", "research_handoff",
        "specialist_resume", "write_done",
    ]
