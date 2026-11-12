"""State khởi tạo một lượt chat (agents/state.initial_state): một nguồn cho Runtime.chat và bộ chuyển đổi eval."""
from typing import get_type_hints

from agentic.agents.state import AgentState, initial_state

# Khoá của AgentState không có trong state khởi tạo, kèm lý do: một node đặt nó trong lượt chạy, và vắng mặt có nghĩa
# như giá trị trống ở mọi chỗ đọc (state.get).
NOT_INITIAL = {
    "decision": "nút orchestrator đặt ở bước định tuyến đầu tiên; thread mới chưa có quyết định",
    "catalog_handoff": "ToolAgent đặt khi cần tra catalog; luật catalog_handoff xoá sau khi dùng",
    "catalog_recovery_domains": "ToolAgent cộng dồn trong lượt để không chuyển tra catalog hai lần cho một miền",
    "research_usage": "nút research ghi ngân sách đã dùng trong lượt",
    "research_work": "nút research ghi kế hoạch và tài liệu trong lượt",
    "research_result": "nút research ghi kết quả trong lượt",
    "research_trace": "nút research ghi vết trong lượt",
    "approved": "nút confirmation đặt khi người dùng duyệt thẻ",
    "reply": "nút answer đặt ở cuối lượt",
    "agent_results": "reducer của các nhánh song song; nút join đặt lại",
    "pending_queue": "delegation đặt khi nhiều bản xem trước chờ thẻ xác nhận",
}


def state(**extra):
    return initial_state(run_id="r-2", user_id="u-1", session_id="s-1", messages=[], **extra)


def test_every_agent_state_key_is_initialised_or_explained():
    declared, initial = set(get_type_hints(AgentState, include_extras=True)), set(state())
    assert declared - initial == set(NOT_INITIAL)
    assert initial <= declared
    assert all(NOT_INITIAL.values())


def test_fresh_turn_defaults():
    fresh = state(mode="normal")
    assert (fresh["status"], fresh["tool_count"], fresh["mode"]) == ("running", 0, "normal")
    assert fresh["route_trace"] == [] and fresh["tool_outputs"] == []
    assert fresh["replying_to_form"] is False and fresh["prev_run_id"] is None
    assert fresh["catalog_choice"] is None and fresh["food_gap"] is None


def test_previous_turn_carries_only_the_card_being_answered():
    gap = {"items": [{"key": "0:0", "query": "bánh mì chảo"}]}
    asked = {"status": "needs_input", "run_id": "r-1", "food_gap": gap, "route_trace": [{"stage": "router"}],
             "decision": {"intent": "LOG_FOOD"}, "tool_count": 3}
    carried = state(previous=asked, food_choices=[{"key": "0:0"}])
    assert carried["food_gap"] == gap and carried["food_choices"] == [{"key": "0:0"}]
    assert carried["replying_to_form"] is True and carried["prev_run_id"] == "r-1"
    assert carried["route_trace"] == [] and carried["tool_count"] == 0 and "decision" not in carried
    # Lượt trước đã xong (không còn hỏi bằng thẻ): thẻ cũ không được mang sang.
    done = state(previous={**asked, "status": "completed"})
    assert done["food_gap"] is None and done["replying_to_form"] is False
