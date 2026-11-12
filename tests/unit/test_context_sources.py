"""Bật/tắt nguồn ngữ cảnh cá nhân (personal_context.sources, settings CONTEXT_SOURCES — chỉ cho thí nghiệm Phase 6).

Một lượt tư vấn cá nhân chạy trên graph thật (model kịch bản, backend giả) chạm cả bốn nguồn: thẻ hồ sơ, sự kiện KG
(retrieve_graph_context), context graph của câu hỏi và các lần đọc backend của nút context. Tắt một nguồn thì đúng
nguồn đó không được gọi, các nguồn khác vẫn chạy.
"""
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from agentic.agents.workflow import build_workflow
from agentic.core.context import RequestContext, request_context
from agentic.knowledge_graph.context import pipeline as context_pipeline
from agentic.knowledge_graph.context.graph import ContextGraph
from agentic.services import personal_context
from agentic.services.personal_context import CONTEXT_PATH, SOURCES
from evaluation.adapters.fixtures import EvalBackend, EvalStore, token_for
from evaluation.adapters.graph_runtime import ScriptedModels, eval_settings

USER = "u-sources"
CARD = {"today": "2026-11-12", "profile": {"age": 28}, "body": {"weight_kg": 70}, "athlete": {}, "running": {},
        "training_4w": {}, "missing": [], "inventory": {"trainings_60d": 0, "body_metrics": 1, "meals_14d": 3}}
ROUTE = {"intent": "GENERAL_CHAT", "action": "answer", "next_agent": "orchestrator", "domain": "meals",
         "instruction": "Trả lời.", "context": {"focus": "summary"}}


class FakeGraph:
    """Dịch vụ KG giả: chỉ đếm lần đọc sự kiện của retrieve_graph_context."""

    def __init__(self):
        self.retrieved = 0

    async def retrieve(self, **kwargs):
        self.retrieved += 1
        return SimpleNamespace(model_dump=lambda mode=None: {"status": "empty", "facts": []})


async def run_turn(monkeypatch, enabled):
    built = []

    async def build(service, models, **kwargs):
        built.append(kwargs["question"])
        return ContextGraph(status="blocked")

    monkeypatch.setattr(context_pipeline, "build", build)
    graph_service, backend = FakeGraph(), EvalBackend(card=CARD)
    graph = build_workflow(ScriptedModels({"decision": [ROUTE]}), EvalStore(), MemorySaver(), None,
                           eval_settings(CONTEXT_SOURCES=enabled), graph_context=graph_service)
    marker = request_context.set(RequestContext(USER, token_for(USER), backend))
    try:
        await graph.ainvoke(
            {"session_id": "s-1", "user_id": USER, "run_id": "r-1", "status": "running", "tool_outputs": [],
             "tool_count": 0, "mode": None, "user_context": None,
             "messages": [HumanMessage(content="Tôi có nên ăn thêm bữa phụ không")]},
            {"configurable": {"thread_id": "t-" + "-".join(enabled)}, "recursion_limit": 40})
    finally:
        request_context.reset(marker)
    names = [call["name"] for call in backend.calls]
    return {
        "card": f"GET {CONTEXT_PATH}" in names,
        "kg_facts": graph_service.retrieved > 0,
        "context_graph": bool(built),
        "backend_reads": "get_nutrition_targets" in names,
    }


async def test_all_sources_on_by_default(monkeypatch):
    assert personal_context.sources(eval_settings()) == frozenset(SOURCES)
    assert personal_context.sources(SimpleNamespace()) == frozenset(SOURCES)
    assert await run_turn(monkeypatch, list(SOURCES)) == dict.fromkeys(SOURCES, True)


@pytest.mark.parametrize("off", SOURCES)
async def test_switching_one_source_off(monkeypatch, off):
    used = await run_turn(monkeypatch, [source for source in SOURCES if source != off])
    assert used == {source: source != off for source in SOURCES}
