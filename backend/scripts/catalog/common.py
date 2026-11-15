"""Đường dẫn và tiện ích dùng chung của pipeline catalog."""
from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx

BACKEND = Path(__file__).resolve().parents[2]
CACHE = BACKEND / ".cache" / "catalog"
HERE = Path(__file__).resolve().parent
USER_AGENT = "HercFit-catalog/1.0 (thesis research; contact via repository owner)"
NIN_BASE = "https://viendinhduong.vn"


def fpt_client() -> httpx.AsyncClient:
    """Client OpenAI-compatible tới FPT AI Marketplace, dùng khoá của agent (backend/agentic/.env)."""
    from agentic.core.app.config import agent_settings

    key = agent_settings.FPT_API_KEY.get_secret_value()
    return httpx.AsyncClient(base_url=agent_settings.FPT_BASE_URL, timeout=180,
                             headers={"Authorization": f"Bearer {key}"})


def image_part(content: bytes, mime: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(content).decode()}"}}


async def chat_json(client: httpx.AsyncClient, model: str, content: str | list, max_tokens: int = 4000) -> Any:
    """Một lượt chat, trả JSON đầu tiên trong câu trả lời (object hoặc array).

    DeepSeek chạy với thinking tắt: kể cả reasoning_effort "low", phần suy luận (~600 token mỗi mục) vẫn ăn hết
    max_tokens của một batch."""
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}]}
    if model.startswith("DeepSeek"):
        body["chat_template_kwargs"] = {"thinking": False}
    for attempt in range(3):
        response = await client.post("/v1/chat/completions", json=body)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
            await asyncio.sleep(5 * (attempt + 1))
            continue
        response.raise_for_status()
        break
    text = response.json()["choices"][0]["message"]["content"] or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        raise ValueError("câu trả lời không có JSON")
    start = min(starts)
    end = text.rfind("}" if text[start] == "{" else "]")
    return json.loads(text[start:end + 1])


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
