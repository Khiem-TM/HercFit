from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator

class ClarifyOption(BaseModel):
    id: str
    label: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=200)
    # Only copied from catalog records returned by tools in this turn, never generated.
    image_url: str | None = None
    ref: dict[str, str] | None = None
    # Text sent back as the user's next message when the option is chosen.
    value: str = Field(max_length=300)

class ClarifyQuestion(BaseModel):
    """One missing piece of information; the client asks these one step at a time."""
    id: str
    # Short topic ("Mục tiêu chính") used to label the answer in the composed reply.
    label: str = Field(max_length=60)
    question: str = Field(max_length=300)
    # 'text' has no options: the user only types the answer.
    mode: Literal['single', 'multiple', 'quick_reply', 'text'] = 'single'
    options: list[ClarifyOption] = Field(default_factory=list, max_length=8)
    allow_free_text: bool = True
    free_text_hint: str | None = Field(default=None, max_length=120)
    # Optional questions can be skipped in the wizard.
    required: bool = True
    min_select: int = Field(default=1, ge=0, le=8)
    max_select: int = Field(default=1, ge=1, le=8)

class Clarification(BaseModel):
    """Human-in-the-loop form: every needs_input reply carries one, answered as a single next message."""
    intro: str | None = Field(default=None, max_length=300)
    questions: list[ClarifyQuestion] = Field(min_length=1, max_length=8)

    @model_validator(mode='before')
    @classmethod
    def _legacy(cls, data):
        # Checkpoints and stored confirm responses from before the form held one top-level question.
        if isinstance(data, dict) and 'questions' not in data and 'question' in data:
            question = {key: value for key, value in data.items() if key != 'intro'}
            return {'intro': data.get('intro'), 'questions': [{'id': 'q1', 'label': 'Trả lời', **question}]}
        return data

class Illustration(BaseModel):
    """Third-party picture found by research; shown for context, stored only via Cloudinary import."""
    url: str
    description: str | None = None

class PendingAction(BaseModel):
    action_id: str
    revision: int
    tool: str
    preview: str
    payload: dict[str, Any]
    payload_hash: str
    expires_at: datetime
    # Server dry-run of the write (names, images, totals, metrics) for the confirmation card.
    display: dict[str, Any] | None = None

class ChatResponse(BaseModel):
    session_id: str
    run_id: str
    reply: str
    status: Literal['completed', 'needs_input', 'pending_confirmation', 'failed']
    intent: str | None = None
    agent_used: str = 'orchestration_agent'
    pending_action: PendingAction | None = None
    clarification: Clarification | None = None
    illustrations: list[Illustration] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
