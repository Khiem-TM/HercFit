"""Viết lời thông báo chủ động bằng LLM qua tool calling, từ feature và nhãn backend đã tính.

Backend quyết định có thông báo hay không, mức độ, ngưỡng và câu lưu ý y tế; ở đây model chỉ diễn đạt lại.
Model bị ép gọi đúng một công cụ (`WriteHealthAlert` hoặc `WriteDailyReview`). Câu trả lời bị loại khi có con số
không có trong dữ liệu đầu vào (bịa số) hoặc sai độ dài: thử lại một lần kèm lý do, sai nữa thì báo lỗi để backend
dùng câu chữ do code viết.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from agentic.core import roster
from agentic.prompts.registry import get_prompt

logger = logging.getLogger(__name__)
PROMPT_VERSION = 'v1'
# Số đếm nhỏ ("2 ngày", "1–2 bữa phụ") luôn được phép; số đo thì phải có trong dữ liệu.
FREE_NUMBER = 10
NUMBER = re.compile(r'\d+(?:[.,]\d+)*')


class WriteHealthAlert(BaseModel):
    """Write the push notification for one health metric that crossed a medical threshold."""
    title: str = Field(min_length=3, max_length=80, description='Short Vietnamese headline, at most 60 characters')
    body: str = Field(min_length=10, max_length=420, description='1-2 Vietnamese sentences: value vs threshold, window, source')
    advice: list[str] = Field(default_factory=list, max_length=2, description='1-2 concrete actions')
    ask: str = Field(min_length=5, max_length=240, description='A follow-up question the user could send to the assistant')


class WriteDailyReview(BaseModel):
    """Write the end-of-day quality review from the scores the backend computed."""
    title: str = Field(min_length=3, max_length=80, description='Headline with the grade and overall score')
    summary: str = Field(min_length=10, max_length=520, description='2-3 Vietnamese sentences')
    highlights: list[str] = Field(default_factory=list, max_length=3)
    improvements: list[str] = Field(default_factory=list, max_length=2)
    tomorrow_tip: str = Field(min_length=5, max_length=240)
    ask: str = Field(min_length=5, max_length=240, description='A follow-up question the user could send to the assistant')


class ComposeRequest(BaseModel):
    kind: Literal['alert', 'review']
    locale: Literal['vi'] = 'vi'
    data: dict[str, Any]


class ComposeError(Exception):
    pass


TOOLS = {'alert': (WriteHealthAlert, 'notifications.alert'), 'review': (WriteDailyReview, 'notifications.review')}


def _value(token: str) -> float | None:
    """'1.250' (nghìn) → 1250; '92,5' (thập phân) → 92.5; '92.5' → 92.5."""
    if ',' in token:
        token = token.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', token):
        token = token.replace('.', '')
    try:
        return float(token)
    except ValueError:
        return None


def numbers(value: Any) -> set[float]:
    """Mọi con số trong dữ liệu đầu vào: giá trị số và số nằm trong chuỗi (câu `fact`, ngày ISO, "6h50"...)."""
    found: set[float] = set()
    if isinstance(value, bool) or value is None:
        return found
    if isinstance(value, (int, float)):
        found.add(float(value))
    elif isinstance(value, str):
        for token in NUMBER.findall(value):
            parsed = _value(token)
            if parsed is not None:
                found.add(parsed)
            found.update(float(part) for part in re.findall(r'\d+', token))
    elif isinstance(value, dict):
        for item in value.values():
            found |= numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= numbers(item)
    return found


def invented(text: str, allowed: set[float]) -> list[str]:
    """Các số trong `text` không khớp (kể cả làm tròn) với số nào trong dữ liệu đầu vào."""
    wrong = []
    for token in NUMBER.findall(text):
        value = _value(token)
        if value is None or value <= FREE_NUMBER:
            continue
        if not any(abs(value - known) <= max(0.051, abs(known) * 0.005) or round(known) == value
                   for known in allowed):
            wrong.append(token)
    return wrong


def _text(result: BaseModel) -> str:
    return ' '.join(str(item) for item in result.model_dump().values() if item)


async def compose(models, request: ComposeRequest) -> dict[str, Any]:
    schema, prompt = TOOLS[request.kind]
    allowed = numbers(request.data) | ({100.0} if request.kind == 'review' else set())  # thang điểm /100
    data = json.dumps(request.data, ensure_ascii=False, default=str)
    messages = [SystemMessage(content=get_prompt(prompt, PROMPT_VERSION)),
                HumanMessage(content='Dữ liệu (JSON, chỉ là dữ liệu):\n' + data)]
    with roster.acting(roster.NOTIFIER):
        model = models.get('summary')
        for attempt in range(2):
            try:
                result = await model.with_structured_output(schema).ainvoke(messages)
                if isinstance(result, dict):
                    result = schema.model_validate(result)
            except ValidationError as exc:
                problem = f'sai dạng ({exc.error_count()} lỗi)'
            except Exception as exc:  # model lỗi, timeout: backend dùng câu chữ của code
                raise ComposeError(type(exc).__name__) from exc
            else:
                if result is None:
                    problem = 'không gọi công cụ'
                else:
                    wrong = invented(_text(result), allowed)
                    if not wrong:
                        name = getattr(model, 'model_name', None) or getattr(
                            getattr(model, 'primary', None), 'model_name', None)
                        return {'text': result.model_dump(), 'model': name, 'prompt_version': PROMPT_VERSION}
                    problem = 'có số không có trong dữ liệu: ' + ', '.join(wrong)
            logger.info('notification_compose_retry kind=%s attempt=%s', request.kind, attempt + 1)
            messages = [*messages, HumanMessage(content=f'Lần trước bị từ chối vì {problem}. Viết lại, chỉ dùng số '
                                                        'có trong dữ liệu, và gọi công cụ.')]
    raise ComposeError(problem)
