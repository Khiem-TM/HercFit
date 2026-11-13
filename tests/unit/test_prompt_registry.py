"""Sổ prompt (agentic/prompts/registry.py, L7.1): mọi lời gọi get_prompt trong code trỏ tới mẫu có đăng ký, và mỗi khoá
chỉ giữ phiên bản đang dùng cùng một phiên bản liền trước."""
import re
from collections import defaultdict
from pathlib import Path

from agentic.prompts.registry import TEMPLATES
from agentic.services import notification_composer, nutrition_lookup

ROOT = Path(__file__).resolve().parents[2]
CALL = re.compile(r"""get_prompt\(\s*["']([\w.]+)["']\s*(?:,\s*["'](v\d+)["'])?\s*\)""")
# Hai nơi gọi bằng hằng phiên bản của module (notification_composer, nutrition_lookup).
DYNAMIC = {("notifications.alert", notification_composer.PROMPT_VERSION),
           ("notifications.review", notification_composer.PROMPT_VERSION),
           ("nutrition.lookup", nutrition_lookup.PROMPT_VERSION)}


def used_templates():
    used = set(DYNAMIC)
    for folder in ("backend", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            if "node_modules" in path.parts or path.name == "registry.py":
                continue
            used |= {(name, version or "v1") for name, version in CALL.findall(path.read_text(errors="ignore"))}
    return used


def test_every_call_is_registered():
    missing = used_templates() - set(TEMPLATES)
    assert not missing


def test_each_key_keeps_at_most_the_used_and_one_previous_version():
    versions = defaultdict(set)
    for name, version in TEMPLATES:
        versions[name].add(version)
    used = defaultdict(set)
    for name, version in used_templates():
        used[name].add(version)
    for name, registered in versions.items():
        assert used[name], f"{name} is registered but never used"
        assert len(registered - used[name]) <= 1, f"{name}: {sorted(registered)}"
