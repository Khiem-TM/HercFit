"""Cấu hình agentic (L5.1): MODE bắt buộc, không còn mặc định "dev"."""
import pytest
from pydantic import ValidationError

from agentic.core.app.config import AgentSettings


def test_mode_is_required(monkeypatch):
    monkeypatch.delenv("MODE", raising=False)
    with pytest.raises(ValidationError) as error:
        AgentSettings(_env_file=None)
    assert any(item["loc"] == ("MODE",) and item["type"] == "missing" for item in error.value.errors())


def test_mode_from_environment(monkeypatch):
    monkeypatch.setenv("MODE", "dev")
    assert AgentSettings(_env_file=None).MODE == "dev"
