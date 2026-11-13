"""Bộ ca E5 (context_sources_eval): mọi ca điền được mốc ngày và có đáp án kỳ vọng; chấm khớp không phân biệt dấu."""
from datetime import date

from evaluation import context_sources_eval as e5


def test_cases_format_and_have_expectations():
    cases = e5.load_cases(e5.anchors_from(date(2026, 11, 12)))
    assert len(cases) >= 33
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert "{" not in case["message"] and case["expect"] and all(case["expect"])
        assert case["decision"]["context"]["focus"]


def test_recall_ignores_accents_and_needs_every_group():
    assert e5.recall([["phở bò chín"], ["5 km", "5000"]], "Hôm đó bạn chạy 5000 m và ăn PHO BO CHIN")
    assert not e5.recall([["phở bò chín"], ["5 km"]], "Hôm đó bạn ăn phở bò chín")


def test_configs_switch_only_listed_sources():
    assert e5.CONFIGS["card"] == ["card"]
    assert all("kg_facts" not in sources for sources in e5.CONFIGS.values())
