"""Xếp hạng có phân biệt dấu cho tìm kiếm catalog (thực phẩm và bài tập).

Tiếng Việt mất nghĩa khi bỏ dấu: "cá", "cà" và "ca" đều chuẩn hoá thành
cùng một chuỗi, và khớp chuỗi con "ca" còn trúng cả
"canh" hay "cacao". SQL thu hẹp ứng viên bằng văn bản đã chuẩn hoá không dấu
và pg_trgm; module này sắp xếp chúng để cách đọc người dùng gõ đứng đầu:

1. đúng tên (có dấu thắng không dấu),
2. tên bắt đầu bằng truy vấn dưới dạng nguyên từ; từ đầu được tính riêng
   vì tên món tiếng Việt bắt đầu bằng danh từ chính ("Cá basa" là cá,
   "Cháo cá" là cháo),
3. mọi từ của truy vấn có mặt dưới dạng nguyên từ,
4. tín hiệu yếu hơn: tiền tố một phần của từ cuối, chuỗi con, tên khác/bí danh,
   độ tương đồng chuỗi, cộng nhẹ cho món của chính người dùng.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from difflib import SequenceMatcher
from typing import Any, TypeVar

T = TypeVar("T")
_WORD = re.compile(r"\w+", re.UNICODE)


def accented(value: str) -> str:
    """Case-folded NFC text that keeps diacritics ('Cá' -> 'cá')."""
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def unaccented(value: str) -> str:
    """Same normalization as the catalog's normalized_* columns ('Cá' -> 'ca')."""
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d").replace("Đ", "d"))
    return " ".join("".join(ch for ch in value if not unicodedata.combining(ch)).split())


def words(value: str) -> list[str]:
    return _WORD.findall(value)


def _prefix_words(query: list[str], name: list[str]) -> bool:
    return bool(query) and name[:len(query)] == query


def _partial_prefix(query: list[str], name: list[str]) -> bool:
    """Mọi từ trừ từ cuối của truy vấn khớp theo thứ tự; từ cuối là tiền tố (đang gõ)."""
    if not query or len(name) < len(query):
        return False
    return name[:len(query) - 1] == query[:-1] and name[len(query) - 1].startswith(query[-1])


def score(query: str, name: str, others: Iterable[str] = (), *, owned: bool = False) -> float:
    qa, qn = accented(query), unaccented(query)
    na, nn = accented(name), unaccented(name)
    if not qn:
        return 0.0
    qa_w, qn_w, na_w, nn_w = words(qa), words(qn), words(na), words(nn)
    total = 0.0
    if na == qa:
        total += 100
    elif nn == qn:
        total += 70
    if _prefix_words(qa_w, na_w):
        total += 40
    elif _prefix_words(qn_w, nn_w):
        total += 25
    elif _partial_prefix(qn_w, nn_w):
        total += 10
    if qa_w and na_w and qa_w[0] == na_w[0]:
        total += 20
    elif qn_w and nn_w and qn_w[0] == nn_w[0]:
        total += 10
    if all(w in na_w for w in qa_w):
        total += 30
    elif all(w in nn_w for w in qn_w):
        total += 15
    elif qn in nn:
        total += 5
    for other in others:
        if other and all(w in words(unaccented(other)) for w in qn_w):
            total += 8
            break
    total += 10 * SequenceMatcher(None, qn, nn).ratio()
    total -= min(len(nn), 60) / 30  # ưu tiên tên ngắn gọn khi mọi thứ khác bằng nhau
    if owned:
        total += 3
    return total


def rank(query: str, items: Sequence[T], *, name: Callable[[T], str],
         others: Callable[[T], Iterable[str]] = lambda _item: (),
         owned: Callable[[T], bool] = lambda _item: False) -> list[T]:
    """Thứ tự tốt-nhất-trước ổn định; bằng điểm thì giữ thứ tự của database (độ tương đồng, id)."""
    scored = [(score(query, name(item) or "", others(item), owned=owned(item)), index, item)
              for index, item in enumerate(items)]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [item for _score, _index, item in scored]


def explain(query: str, items: Sequence[Any], *, name: Callable[[Any], str]) -> list[tuple[str, float]]:
    """Hàm hỗ trợ gỡ lỗi: các cặp (tên, điểm) theo thứ tự xếp hạng."""
    return [(name(item), round(score(query, name(item)), 2)) for item in rank(query, items, name=name)]
