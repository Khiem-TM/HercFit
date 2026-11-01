"""Accent-aware ranking for catalog search (foods and exercises).

Vietnamese loses meaning without diacritics: "cá" (fish), "cà" (eggplant) and
"ca" all normalize to the same string, and a substring match on "ca" also hits
"canh" or "cacao". SQL narrows candidates with the accent-free normalized text
and pg_trgm; this module orders them so the reading the user typed comes first:

1. exact name (accented beats accent-free),
2. name starting with the query as whole words; the head word counts on its
   own because Vietnamese dish names lead with the head noun ("Cá basa" is fish,
   "Cháo cá" is porridge),
3. every query word present as a whole word,
4. weaker signals: partial last-word prefix, substring, other names/aliases,
   string similarity, a small boost for the user's own items.
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
    """All but the last query word match in order; the last is a prefix (typing)."""
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
    total -= min(len(nn), 60) / 30  # prefer concise names when everything else ties
    if owned:
        total += 3
    return total


def rank(query: str, items: Sequence[T], *, name: Callable[[T], str],
         others: Callable[[T], Iterable[str]] = lambda _item: (),
         owned: Callable[[T], bool] = lambda _item: False) -> list[T]:
    """Stable best-first order; ties keep the database order (similarity, id)."""
    scored = [(score(query, name(item) or "", others(item), owned=owned(item)), index, item)
              for index, item in enumerate(items)]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [item for _score, _index, item in scored]


def explain(query: str, items: Sequence[Any], *, name: Callable[[Any], str]) -> list[tuple[str, float]]:
    """Debug helper: (name, score) pairs in ranked order."""
    return [(name(item), round(score(query, name(item)), 2)) for item in rank(query, items, name=name)]
