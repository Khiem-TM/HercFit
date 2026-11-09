"""Viết lời cho cảnh báo chỉ số và đánh giá ngày: LLM (service agentic, qua tool calling) hoặc câu chữ do code.

Backend không phụ thuộc nhà cung cấp model: nó gửi feature và nhãn đã tính sang agentic
(POST /internal/notifications/compose, ký HMAC như core/service_auth) và nhận lại lời đã viết. Dữ liệu thiết bị
chỉ rời backend khi người dùng đã cho trợ lý dùng nó (consent "assistant"/"device"). Không có consent,
agentic chưa cấu hình, lỗi, quá thời gian hay trả về sai dạng: dùng câu chữ do code viết, nên thông báo
luôn được gửi. Mức độ, ngưỡng và dòng lưu ý y tế luôn do code quyết định, không phải LLM.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError

from core import service_auth
from core.settings import settings
from domains.analytics.services.day_review import DayReview
from domains.analytics.services.health_rules import catalog
from domains.analytics.services.health_rules.evaluate import Profile, Signal, ddmm
from domains.identity import consent
from domains.notifications.services.drafts import Draft

logger = logging.getLogger(__name__)
COMPOSE_PATH = "/internal/notifications/compose"
PRIORITY = {"urgent": 1, "warn": 1, "info": 3}


class AlertText(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    body: str = Field(min_length=10, max_length=420)
    advice: list[str] = Field(default_factory=list, max_length=2)
    ask: str = Field(min_length=5, max_length=240)


class ReviewText(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    summary: str = Field(min_length=10, max_length=520)
    highlights: list[str] = Field(default_factory=list, max_length=3)
    improvements: list[str] = Field(default_factory=list, max_length=2)
    tomorrow_tip: str = Field(min_length=5, max_length=240)
    ask: str = Field(min_length=5, max_length=240)


class Composed(BaseModel):
    text: dict[str, Any]
    model: str | None = None
    prompt_version: str | None = None


def profile_summary(profile: Profile) -> dict[str, Any]:
    """Thể trạng ở mức đủ để chọn giọng văn; không gửi họ tên, email hay ngày sinh."""
    return {"sex": profile.sex, "age": profile.age, "goal": profile.goal, "trained": profile.trained}


async def _llm(session, user_id: UUID, kind: str, data: dict[str, Any]) -> Composed | None:
    secret = settings.AGENT_SERVICE_SECRET.get_secret_value() if settings.AGENT_SERVICE_SECRET else ""
    if not settings.AGENTIC_INTERNAL_URL or not secret:
        return None
    if not (await consent.load(session, user_id)).allows("device"):
        return None
    body = json.dumps({"kind": kind, "locale": "vi", "data": data}, ensure_ascii=False, default=str).encode()
    headers = {"Content-Type": "application/json", "X-HercFit-User": str(user_id),
               service_auth.HEADER: service_auth.sign(secret, "POST", COMPOSE_PATH, str(user_id), body)}
    try:
        async with httpx.AsyncClient(base_url=settings.AGENTIC_INTERNAL_URL,
                                     timeout=settings.NOTIFICATION_COMPOSE_TIMEOUT_SECONDS) as client:
            response = await client.post(COMPOSE_PATH, content=body, headers=headers)
        response.raise_for_status()
        return Composed.model_validate(response.json())
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        logger.warning("notification_compose_fallback kind=%s error=%s", kind, type(exc).__name__)
        return None


def _notes(severity: str) -> list[str]:
    if severity == "urgent":
        return [catalog.URGENT_NOTE, catalog.DISCLAIMER]
    return [catalog.DISCLAIMER] if severity == "warn" else []


def _alert_ask(signal: Signal) -> str:
    return f"Giải thích giúp mình cảnh báo «{signal.title}» và mình nên làm gì tiếp theo."


async def alert(session, user_id: UUID, signal: Signal, profile: Profile) -> Draft:
    features = signal.features()
    composed = await _llm(session, user_id, "alert", {"profile": profile_summary(profile), "signal": features})
    text = None
    if composed is not None:
        try:
            text = AlertText.model_validate(composed.text)
        except ValidationError:
            text = None
    by = "llm" if text is not None else "template"
    text = text or AlertText(title=signal.title, body=signal.fact, advice=[signal.advice], ask=_alert_ask(signal))
    body = " ".join([text.body, *_notes(signal.severity)])
    payload = {
        "severity": signal.severity, "severity_rank": catalog.SEVERITY_RANK[signal.severity],
        "group": signal.meta.group, "rule": signal.rule, "features": features, "advice": text.advice, "ask": text.ask,
        "composer": {"by": by, "model": composed.model if by == "llm" else None,
                     "prompt_version": composed.prompt_version if by == "llm" else None},
    }
    return Draft("alert", f"ALERT_{signal.rule.upper()}", PRIORITY[signal.severity],
                 f"alert:{signal.rule}:{signal.severity}:{signal.anchor.isoformat()}", text.title, body, payload,
                 ttl_days=3, urgent=signal.severity == "urgent")


def _review_template(review: DayReview, tomorrow: list[str]) -> ReviewText:
    day = ddmm(review.date)
    if not review.enough:
        return ReviewText(
            title=f"Chưa đủ dữ liệu để đánh giá ngày {day}",
            summary="Hôm nay HercFit chưa có đủ dữ liệu (cần ít nhất hai trong các mặt dinh dưỡng, vận động, giấc ngủ, "
                    "hồi phục, lịch tập) để chấm điểm ngày.",
            tomorrow_tip="Ngày mai ghi bữa ăn và đeo thiết bị khi ngủ để có bản đánh giá đầy đủ.",
            ask="Mình nên ghi những dữ liệu nào để HercFit đánh giá được một ngày?")
    from domains.analytics.services.day_review import TIPS

    scored = [d for d in review.dimensions if d.score is not None]
    weakest = review.weakest()
    tip = TIPS[weakest.id] if weakest is not None and weakest.score is not None and weakest.score < 80 else \
        "Giữ nhịp như hôm nay."
    if tomorrow:
        tip += f" Ngày mai bạn có buổi {', '.join(tomorrow)}."
    return ReviewText(
        title=f"Đánh giá ngày {day}: {review.grade} · {review.score}/100",
        summary=" ".join(f"{d.as_dict()['label']}: {d.detail}" for d in scored),
        highlights=[f"{d.as_dict()['label']}: {d.detail}" for d in scored if d.rating == "good"][:3],
        improvements=[f"{d.as_dict()['label']}: {d.detail}" for d in scored if d.rating == "poor"][:2],
        tomorrow_tip=tip, ask="Nhận xét chi tiết hơn về ngày hôm nay của mình và gợi ý cho ngày mai.")


async def review(session, user_id: UUID, day_review: DayReview, profile: Profile, *, alerts: list[str],
                 tomorrow: list[str]) -> Draft:
    data = {"profile": profile_summary(profile), "review": day_review.as_dict(), "alerts_today": alerts,
            "tomorrow_sessions": tomorrow}
    composed = await _llm(session, user_id, "review", data) if day_review.enough else None
    text = None
    if composed is not None:
        try:
            text = ReviewText.model_validate(composed.text)
        except ValidationError:
            text = None
    by = "llm" if text is not None else "template"
    text = text or _review_template(day_review, tomorrow)
    payload = {
        "review": day_review.as_dict(), "highlights": text.highlights, "improvements": text.improvements,
        "tomorrow_tip": text.tomorrow_tip, "ask": text.ask, "alerts": alerts,
        "composer": {"by": by, "model": composed.model if by == "llm" else None,
                     "prompt_version": composed.prompt_version if by == "llm" else None},
    }
    return Draft("review", "DAY_REVIEW", 2, f"review:{day_review.date.isoformat()}", text.title, text.summary,
                 payload, ttl_days=2)
