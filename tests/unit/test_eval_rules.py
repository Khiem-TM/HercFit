"""Evaluator code_rules của bộ ca chuẩn: luật phải kích hoạt, luật không được kích hoạt và intent của quyết định."""
from types import SimpleNamespace

import pytest

from evaluation.evaluators.agent import ExpectedRules

RECORD = {"route_rules": ["personalize", "plan_mode_only"], "intents": ["SPORTS_KNOWLEDGE_QA", "clarification"]}


def score(reference):
    result = ExpectedRules().evaluate(SimpleNamespace(output=RECORD, expected_output=reference))
    return result["code_rules"].value if result else None


@pytest.mark.parametrize(("reference", "passed"), [
    ({"route_rules": ["plan_mode_only"]}, True),
    ({"route_rules": ["write_done"]}, False),
    ({"rules_forbidden": ["fan_out"]}, True),
    ({"rules_forbidden": ["personalize"]}, False),
    ({"intents": ["clarification"]}, True),
    ({"intents": ["SAFETY"]}, False),
    ({"intents_forbidden": ["limit"]}, True),
    ({"intents_forbidden": ["clarification"]}, False),
    ({"route_rules": ["personalize"], "intents_forbidden": ["clarification"]}, False),
])
def test_code_rules(reference, passed):
    assert score(reference) is passed


def test_case_without_rule_labels_is_not_scored():
    assert score({"final_status": "completed"}) is None
