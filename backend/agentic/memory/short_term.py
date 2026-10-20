"""Short-term session context management and sliding window message history."""

from typing import Any

from config.settings import agent_settings
from core.llm import AnyMessage, HumanMessage


class ShortTermMemory:
    """Manages current session conversation history and sliding window trimming."""

    def __init__(self, max_messages: int | None = None) -> None:
        self.max_messages = (
            max_messages
            if max_messages is not None
            else agent_settings.SHORT_TERM_MAX_MESSAGES
        )
        self._sessions: dict[str, list[AnyMessage]] = {}

    def get_session_messages(self, session_id: str) -> list[AnyMessage]:
        messages = self._sessions.get(session_id, [])
        return self.trim(messages)

    def append_message(self, session_id: str, message: AnyMessage) -> list[AnyMessage]:
        bucket = self._sessions.setdefault(session_id, [])
        bucket.append(message)
        trimmed = self.trim(bucket)
        self._sessions[session_id] = trimmed
        return list(trimmed)

    def append_user_text(self, session_id: str, text: str) -> list[AnyMessage]:
        return self.append_message(session_id, HumanMessage(content=text))

    def trim(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        if len(messages) <= self.max_messages:
            return list(messages)
        return list(messages[-self.max_messages :])

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def to_summary_dict(self, session_id: str) -> dict[str, Any]:
        msgs = self.get_session_messages(session_id)
        return {
            "session_id": session_id,
            "message_count": len(msgs),
            "messages": [
                {
                    "role": getattr(m, "type", "unknown"),
                    "content": str(m.content),
                    "name": getattr(m, "name", None),
                }
                for m in msgs
            ],
        }
