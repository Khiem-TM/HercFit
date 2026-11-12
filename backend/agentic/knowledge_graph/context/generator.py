"""Context Agent: viết Cypher chỉ đọc cho một câu hỏi khi chưa có mẫu phù hợp (text-to-Cypher)."""

import re
from contextlib import nullcontext

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agentic.core import roster
from agentic.prompts.registry import get_prompt

from ..schema import describe
from .templates import SEEDS_BY_ID

EXAMPLES = (
    "meals.list",
    "foods.top",
    "exercise.history",
    "nutrition.periods",
    "health.days",
    "session.trace",
)
FENCE = re.compile(r"^```(?:cypher)?\s*|\s*```$", re.I)


class CypherDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cypher: str = Field(
        description="Exactly one read-only Cypher query following the rules and schema"
    )


def _prompt():
    examples = "\n\n".join(
        f"// {name}\n{SEEDS_BY_ID[name].cypher}" for name in EXAMPLES if name in SEEDS_BY_ID
    )
    return (
        get_prompt("context.cypher", "v1")
        .replace("{schema}", describe())
        .replace("{examples}", examples)
    )


PROMPT = _prompt()


async def generate(models, *, question, intent, domain, focus, frame, terms, rejected=None):
    """Văn bản Cypher (chưa kiểm tra). `rejected` = (truy vấn trước, lý do) để model tự sửa đúng một lần."""
    lines = [
        "Câu hỏi của người dùng: " + question,
        f"Ý định: {intent or '-'} · miền: {domain or '-'} · focus: {focus}",
        f"Thời gian đã chuẩn hoá: $start = {frame.start}, $end = {frame.end}, $grain = '{frame.grain}'",
        "$terms = " + (", ".join(terms) if terms else "(không có)"),
    ]
    if rejected:
        previous, reason = rejected
        lines += [
            "Truy vấn trước bị từ chối: " + reason,
            previous,
            "Viết lại truy vấn đúng quy tắc.",
        ]
    # Lần đầu dùng model riêng của Context Agent (AGENT_MODELS["context"], nhanh); lần tự sửa sau khi bị validator hay
    # Neo4j từ chối nâng lên model của vai trò, vì model đã viết sai một lần dễ sai lại theo cùng cách.
    with roster.acting(roster.CONTEXT), roster.escalate() if rejected else nullcontext():
        draft = await (
            models.get("decision")
            .with_structured_output(CypherDraft)
            .ainvoke([SystemMessage(content=PROMPT), HumanMessage(content="\n".join(lines))])
        )
    return FENCE.sub("", (draft.cypher if draft else "").strip())
