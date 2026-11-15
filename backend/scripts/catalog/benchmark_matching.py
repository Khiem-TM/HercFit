"""Đo tỉ lệ khớp tên chính xác của catalog với các cụm người dùng hay gõ khi ghi bữa (chỉ đọc DB).

Mỗi cụm đi đúng đường ghi bữa nhanh: ``FoodItem.list_visible(names=[cụm])`` (như tool list_foods) rồi
``meal_logging.name_matches``. Một cụm "khớp" khi đúng một bản ghi trùng tên/alias; "mơ hồ" khi nhiều bản ghi;
"có khẩu phần" khi bản ghi khớp quy đổi được "1 tô/1 cái" (SERVING). Chạy trước và sau migration 0035 để so sánh.

    python -m scripts.catalog.benchmark_matching [--out before.json]
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from agentic.services.meal_logging import measure, name_matches
from core.database import get_session_factory
from domains.catalog.models.foods import FoodItem
from domains.catalog.schemas.foods import FoodRead
from scripts.catalog.common import write_json

PHRASES = (
    # món
    "phở bò", "phở gà", "bún chả", "bún bò huế", "bún riêu", "bún đậu mắm tôm", "bánh mì", "bánh mì pate",
    "bánh mì trứng", "bánh mì thịt", "xôi xéo", "xôi pate", "xôi gà", "bánh cuốn", "bánh bao nhân thịt",
    "cơm rang thập cẩm", "cơm rang dưa bò", "cơm gà", "cơm tấm", "miến gà", "miến ngan", "mì xào bò", "hủ tiếu",
    "bánh canh cua", "cháo gà", "cháo lòng", "cháo sườn", "nem rán", "chả giò", "nem nướng", "gỏi cuốn",
    "canh chua cá", "canh rau muống", "rau muống xào tỏi", "thịt kho trứng", "cá kho tộ", "gà luộc", "thịt luộc",
    "đậu phụ sốt cà chua", "trứng rán", "trứng chiên", "chè đỗ đen", "chè thái", "sữa chua", "bánh flan",
    "bánh xèo", "lẩu thái", "pizza", "hamburger", "gà rán",
    # thực phẩm cơ bản
    "cơm trắng", "cơm", "trứng gà luộc", "trứng luộc", "trứng vịt lộn", "ức gà luộc", "ức gà", "thịt bò",
    "thịt lợn nạc", "thịt heo", "cá hồi", "tôm", "đậu phụ", "khoai lang luộc", "ngô luộc", "chuối", "táo", "cam",
    "xoài", "dưa hấu", "bơ", "sữa tươi", "sữa đậu nành", "sữa đặc", "bánh mì sandwich", "yến mạch", "gạo lứt",
    "khoai tây", "rau muống", "cải bắp", "cà chua", "dưa chuột", "lạc", "hạt điều", "mật ong", "đường", "dầu ăn",
    "nước mắm",
    # đồ uống, sản phẩm
    "trà đá", "cà phê đen", "cà phê sữa đá", "trà sữa", "nước cam", "nước dừa", "bia", "coca", "pepsi", "sting",
    "mì hảo hảo", "mì tôm", "sữa vinamilk", "milo", "choco pie",
)


async def run(out: Path | None) -> None:
    results = {}
    async with get_session_factory()() as session:
        for phrase in PHRASES:
            foods = await FoodItem.list_visible(session, user_id=uuid.uuid4(), names=[phrase], limit=20)
            rows = [FoodRead.model_validate(food).model_dump(mode="json") for food in foods]
            hits = [row for row in rows if name_matches(phrase, row)]
            results[phrase] = {"hits": [row["name_vi"] for row in hits],
                               "serving": len(hits) == 1 and measure(hits[0], 1, "SERVING") is not None,
                               "top": [row["name_vi"] for row in rows[:3]]}
    exact = [p for p, r in results.items() if len(r["hits"]) == 1]
    ambiguous = [p for p, r in results.items() if len(r["hits"]) > 1]
    serving = [p for p, r in results.items() if r["serving"]]
    summary = {"phrases": len(PHRASES), "exact": len(exact), "ambiguous": len(ambiguous), "serving": len(serving),
               "missing": [p for p, r in results.items() if not r["hits"]], "ambiguous_phrases": ambiguous}
    print(f"exact {len(exact)}/{len(PHRASES)} ({len(exact) / len(PHRASES):.0%}), ambiguous {len(ambiguous)}, "
          f"exact with household portion {len(serving)}")
    print("missing:", ", ".join(summary["missing"]))
    print("ambiguous:", ", ".join(ambiguous))
    if out:
        write_json(out, {"summary": summary, "results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    asyncio.run(run(parser.parse_args().out))
