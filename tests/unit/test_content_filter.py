"""Bộ lọc an toàn tất định (agentic/security/content_filter.py): mỗi nhóm một ca bị bắt và một ca gần giống thì không."""
import pytest

from agentic.security.content_filter import assess


@pytest.mark.parametrize(("text", "category", "level"), [
    ("Dạo này tôi muốn chết, không thiết gì nữa", "self_harm", "block"),
    ("Ăn xong tôi thường tự gây nôn để giảm cân", "eating_disorder", "block"),
    ("Tôi bị đau ngực khi chạy bộ sáng nay", "red_flag_symptom", "caution"),
    ("Tôi muốn ăn 800 kcal mỗi ngày để giảm cân", "extreme_deficit", "block"),
])
def test_flagged(text, category, level):
    verdict = assess(text)
    assert verdict is not None
    assert (verdict.category, verdict.level) == (category, level)


@pytest.mark.parametrize("text", [
    "Tôi tự tin sẽ giảm được 3 kg trong 2 tháng",      # "tự tin" không phải "tự tử"
    "Tập xong tôi hơi buồn nôn, nên ăn gì trước buổi tập?",
    "Hôm nay tập ngực và tập ngắt quãng 20 phút",    # nhóm cơ ngực, không phải đau ngực
    "Bữa trưa của tôi khoảng 800 kcal",              # năng lượng một bữa, không phải tổng ngày
    "Tôi muốn ăn 1500 kcal mỗi ngày để giảm cân",
])
def test_not_flagged(text):
    assert assess(text) is None
