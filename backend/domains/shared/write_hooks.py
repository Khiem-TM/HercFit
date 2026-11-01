"""Business write hooks: integrations react to domain writes inside the same transaction.

Domains call `emit(...)` after a create/update/delete; a provider integration (for
example the Google Health exporter) registers a hook and writes its outbox rows in
the caller's transaction, so the business change and the work to propagate it
commit together or not at all. Domains never import an integration.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

Hook = Callable[..., Awaitable[Any]]
_hooks: list[Hook] = []


def register(hook: Hook) -> None:
    if hook not in _hooks:
        _hooks.append(hook)


async def emit(session, user_id: UUID, aggregate_type: str, entity: Any, op: str, **extra: Any) -> None:
    for hook in _hooks:
        await hook(session, user_id, aggregate_type, entity, op, **extra)


# Previewers describe what a write would cause outside HercFit (e.g. the Google data point),
# so a confirmation card can show it and the confirmed write can be bound to it.
_previewers: list[Hook] = []


def register_previewer(previewer: Hook) -> None:
    if previewer not in _previewers:
        _previewers.append(previewer)


async def preview(session, user_id: UUID, aggregate_type: str, entity: Any) -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for previewer in _previewers:
        effects.extend(await previewer(session, user_id, aggregate_type, entity))
    return effects


def effects_sha256(effects: list[dict[str, Any]]) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(effects, sort_keys=True, default=str).encode()).hexdigest()
