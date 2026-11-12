"""Đường ghi bữa do code dựng (agentic/services/meal_logging.py): món nào code tự chọn được, món nào phải hỏi bằng thẻ."""
from agentic.services.meal_logging import payload, unmatched

PHO = {"id": "pho", "name_vi": "Phở bò", "serving_unit": "G", "portions": [{"label": "1 tô", "quantity": 600, "unit": "G"}]}
RICE = {"id": "rice", "name_vi": "Cơm trắng", "serving_unit": "G"}
RICE_2 = {"id": "rice-2", "name_vi": "Cơm trắng", "serving_unit": "G"}


def meal(*items, consumed_at="2026-11-02T12:00:00+07:00"):
    return {"name": "Bữa trưa", "consumed_at": consumed_at,
            "items": [{"food": food, "quantity": quantity, "unit": unit} for food, quantity, unit in items]}


def test_exact_match_with_portion_needs_no_card():
    assert unmatched(meal(("phở bò", 1, "SERVING")), [PHO]) == []


def test_items_the_code_cannot_pick_are_returned():
    draft = meal(("phở bò", 1, "SERVING"),       # khớp chắc chắn
                 ("cơm trắng", 1, "SERVING"),    # "1 bát" mà món không có khẩu phần
                 ("phở bò", None, None),          # thiếu lượng
                 ("bánh mì chảo", 100, "G"))      # catalog chưa có
    assert [position for position, _ in unmatched(draft, [PHO, RICE])] == [1, 2, 3]


def test_duplicate_names_are_ambiguous_and_picks_are_skipped():
    draft = meal(("cơm trắng", 200, "G"), ("cơm trắng", 100, "G"))
    assert [position for position, _ in unmatched(draft, [RICE, RICE_2])] == [0, 1]
    picked = {"0:0": {"food_id": "rice", "quantity": 200, "unit": "G"}}
    assert [position for position, _ in unmatched(draft, [RICE, RICE_2], picked)] == [1]


def test_payload_without_time_lets_backend_use_now():
    body = payload(meal(("phở bò", 1, "SERVING"), consumed_at=None), [{"food_id": "pho", "quantity": 600, "unit": "G"}])
    assert "consumed_at" not in body


def test_payload_naive_time_uses_meal_timezone():
    body = payload(meal(("phở bò", 1, "SERVING"), consumed_at="2026-11-02T12:00:00"), [])
    assert body["consumed_at"] == "2026-11-02T12:00:00+07:00"
