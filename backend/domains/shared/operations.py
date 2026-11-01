"""Operations: the user-visible handle of an asynchronous command (sync, export, history export).

An operation's state is derived from its jobs, so it can never disagree with them:
PENDING (nothing started), RUNNING, SUCCEEDED, PARTIAL (some jobs need attention or
were cancelled), FAILED (none succeeded), UNCERTAIN (an export whose outcome at the
provider could not be verified).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from domains.shared.models.basemodel import uuid7

KINDS = ("health.sync", "health.export", "health.history_export", "health.reauthorize")


async def create(session, user_id: UUID, kind: str, result: dict[str, Any] | None = None) -> UUID:
    if kind not in KINDS:
        raise ValueError(kind)
    operation_id = uuid7()
    import json
    await session.execute(text(
        "INSERT INTO operations (id, user_id, kind, result) VALUES (:id, :user, :kind, CAST(:result AS jsonb))"),
        {"id": operation_id, "user": user_id, "kind": kind, "result": json.dumps(result or {})})
    return operation_id


def derive(states: dict[str, int], uncertain: int = 0) -> str:
    total = sum(states.values())
    if uncertain:
        return "UNCERTAIN"
    if total == 0:
        return "PENDING"
    active = states.get("QUEUED", 0) + states.get("RETRY", 0) + states.get("RUNNING", 0)
    if active:
        return "RUNNING" if states.get("RUNNING", 0) or total > active else "PENDING"
    succeeded = states.get("SUCCEEDED", 0)
    if succeeded == total:
        return "SUCCEEDED"
    return "PARTIAL" if succeeded else "FAILED"


async def read(session, user_id: UUID, operation_id: UUID) -> dict[str, Any]:
    row = (await session.execute(text(
        "SELECT id, kind, created_at, result FROM operations WHERE id = :id AND user_id = :user"),
        {"id": operation_id, "user": user_id})).first()
    if row is None:
        raise HTTPException(404, "Operation not found")
    jobs = (await session.execute(text("""
        SELECT kind, data_type, state, error_class, error_code, progress -> 'result' AS result
        FROM jobs WHERE operation_id = :id OR root_id IN (SELECT id FROM jobs WHERE operation_id = :id)
        ORDER BY created_at"""), {"id": operation_id})).mappings().all()
    exports = (await session.execute(text(
        "SELECT state, count(*) AS n FROM export_outbox WHERE operation_id = :id GROUP BY state"),
        {"id": operation_id})).mappings().all()
    states: dict[str, int] = {}
    for job in jobs:
        states[job["state"]] = states.get(job["state"], 0) + 1
    export_states = {item["state"]: item["n"] for item in exports}
    uncertain = export_states.get("UNCERTAIN", 0)
    if exports:
        pending = sum(n for state, n in export_states.items() if state in ("PENDING", "DISPATCHING", "SUBMITTED",
                                                                             "VERIFYING"))
        done = export_states.get("CONFIRMED", 0)
        states["QUEUED"] = states.get("QUEUED", 0) + pending
        states["SUCCEEDED"] = states.get("SUCCEEDED", 0) + done
        failed = sum(n for state, n in export_states.items() if state in ("FAILED", "CONFLICT", "BLOCKED_PERMISSION"))
        states["NEEDS_ATTENTION"] = states.get("NEEDS_ATTENTION", 0) + failed
    return {
        "id": row.id, "kind": row.kind, "state": derive(states, uncertain), "created_at": row.created_at,
        "jobs": {"total": len(jobs), "by_state": states},
        "steps": [{"kind": job["kind"], "data_type": job["data_type"], "state": job["state"],
                   "error": job["error_code"], "result": job["result"]} for job in jobs[:200]],
        "exports": export_states,
    }
