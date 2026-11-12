"""Lệnh ghi đơn giản nhận diện bằng code (agentic/services/simple_writes.py)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import HumanMessage

from agentic.services.simple_writes import recognize, simple_route

NOW = datetime(2026, 11, 12, 8, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def norm(text):
    return " ".join(text.strip().casefold().split())


@pytest.mark.parametrize(("text", "kg"), [
    ("cân nặng 68,2 kg", 68.2), ("Sáng nay cân 68.2kg", 68.2), ("tôi nặng 68 kg", 68.0),
    ("hôm nay tôi nặng 70 kg", 70.0), ("cân nặng là 71,5 kg.", 71.5),
])
def test_weight(text, kg):
    assert recognize(norm(text), NOW) == ("metrics", "LOG_METRICS", "create_metrics", {"weight_kg": kg})


@pytest.mark.parametrize(("text", "ml"), [
    ("uống 500 ml nước", 500), ("vừa uống 1 ly nước 250ml", 250), ("Tôi vừa uống 1 lít nước", 1000),
    ("uống 300ml", 300), ("mình mới uống 0,5 l nước", 500),
])
def test_water(text, ml):
    domain, intent, tool, args = recognize(norm(text), NOW)
    assert (domain, intent, tool, args["amount_ml"]) == ("meals", "LOG_WATER", "log_water", ml)


@pytest.mark.parametrize(("text", "start", "end"), [
    ("ngủ từ 23h đến 6h30", "2026-11-11T23:00:00+07:00", "2026-11-12T06:30:00+07:00"),
    ("đêm qua ngủ 23:15 tới 6:00", "2026-11-11T23:15:00+07:00", "2026-11-12T06:00:00+07:00"),
    ("tối qua tôi ngủ lúc 22 giờ đến 5 giờ 45", "2026-11-11T22:00:00+07:00", "2026-11-12T05:45:00+07:00"),
    ("ngủ từ 1h đến 7h", "2026-11-12T01:00:00+07:00", "2026-11-12T07:00:00+07:00"),
    # Giờ thức dậy chưa tới hôm nay (8:00) thì là đêm trước.
    ("ngủ từ 23h đến 9h", "2026-11-10T23:00:00+07:00", "2026-11-11T09:00:00+07:00"),
])
def test_sleep(text, start, end):
    domain, intent, tool, args = recognize(norm(text), NOW)
    assert (domain, intent, tool) == ("metrics", "LOG_SLEEP", "log_sleep")
    assert (args["started_at"], args["ended_at"]) == (start, end)


@pytest.mark.parametrize("text", [
    "cần nặng 68 kg thì ăn bao nhiêu calo?", "tôi muốn nặng 60 kg", "nặng 68 kg?", "cân nặng 68 kg và cao 170 cm",
    "cân nặng 5 kg",
    "uống 500 ml nước có đủ không", "uống bao nhiêu ml nước", "uống 500 ml nước và ăn 1 quả chuối", "nếu uống 2 lít nước",
    "ngủ từ 23h đến 6h có tốt không", "nếu ngủ từ 23h đến 6h", "cần ngủ từ 22h đến 6h", "ngủ từ 23h đến 6h30 rồi chạy 5 km",
])
def test_not_a_simple_write(text):
    assert recognize(norm(text), NOW) is None


def state(text, **extra):
    return {"messages": [HumanMessage(content=text)], "run_id": "r-1", "tool_outputs": [], **extra}


def test_route_carries_the_prebuilt_call():
    decision = simple_route(state("cân nặng 68,2 kg"), NOW)
    assert (decision["action"], decision["domain"], decision["intent"]) == ("tool", "metrics", "LOG_METRICS")
    assert decision["code_call"] == {"name": "create_metrics", "args": {"weight_kg": 68.2}}


@pytest.mark.parametrize("extra", [
    {"status": "needs_input"}, {"pending_action": {"action_id": "a"}}, {"tool_outputs": [{"tool": "x"}]},
    {"turn": {"run_id": "r-1"}},
])
def test_only_on_the_first_routing_step(extra):
    assert simple_route(state("cân nặng 68,2 kg", **extra), NOW) is None
