"""Quyền database tối thiểu (L5.2): áp backend/scripts/db_roles.sql bằng psql thật trên database test.

Role là đối tượng của cả cluster, nên test dùng tên riêng (hercfit_agent_test, hercfit_kg_test) để không bao giờ đổi
mật khẩu của role thật mà dev dùng; role test bị xoá sau khi test xong.
"""
import os
import shutil
import subprocess

import psycopg
import pytest
from psycopg import errors
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from core.database import get_postgres_connection_string

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "scripts", "db_roles.sql")
AGENT, KG, PASSWORD = "hercfit_agent_test", "hercfit_kg_test", "role-test-only-0001"
BUSINESS = ("meals", "users", "health_points")

pytestmark = pytest.mark.skipif(shutil.which("psql") is None, reason="psql không có trên máy")


def apply(**variables):
    info = conninfo_to_dict(get_postgres_connection_string())
    assert info["dbname"].endswith("_test")
    command = ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", info["host"], "-p", str(info["port"]),
               "-U", info["user"], "-d", info["dbname"], "-f", SCRIPT]
    for name, value in variables.items():
        command[1:1] = ["-v", f"{name}={value}"]
    return subprocess.run(command, capture_output=True, text=True,
                          env={**os.environ, "PGPASSWORD": info.get("password") or ""})


def connect(role):
    return psycopg.connect(make_conninfo(get_postgres_connection_string(), user=role, password=PASSWORD),
                           autocommit=True)


def denied(conn, statement):
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)


@pytest.fixture(scope="module")
def roles(agent_pool):
    # agent_pool đã chạy migration agent: các bảng agent_* và checkpoint có sẵn trước khi cấp quyền.
    result = apply(agent_role=AGENT, kg_role=KG, agent_password=PASSWORD, kg_password=PASSWORD)
    assert result.returncode == 0, result.stderr
    yield
    with psycopg.connect(get_postgres_connection_string(), autocommit=True) as conn:
        for role in (AGENT, KG):
            conn.execute(f"DROP OWNED BY {role}")
            conn.execute(f"DROP ROLE {role}")


def test_script_is_rerunnable_and_needs_passwords(roles):
    again = apply(agent_role=AGENT, kg_role=KG, agent_password=PASSWORD, kg_password=PASSWORD)
    assert again.returncode == 0, again.stderr
    assert PASSWORD not in again.stdout
    missing = apply(agent_role=AGENT, kg_role=KG, agent_password=PASSWORD, kg_password="")
    assert missing.returncode != 0 and "kg_password" in missing.stderr


def test_agent_role_reaches_only_agent_tables(roles):
    with connect(AGENT) as conn:
        for table in BUSINESS:
            denied(conn, f"SELECT count(*) FROM {table}")
        conn.execute("SELECT count(*) FROM agent_actions")
        conn.execute("INSERT INTO agent_actions SELECT * FROM agent_actions WHERE false")
        conn.execute("UPDATE agent_actions SET status = status WHERE false")
        conn.execute("DELETE FROM agent_actions WHERE false")
        for table in ("checkpoints", "checkpoint_writes", "kg_outbox", "kg_query_templates", "agent_sessions"):
            conn.execute(f"SELECT count(*) FROM {table}")
        conn.execute("SELECT count(*) FROM domain_events")
        denied(conn, "DELETE FROM domain_events WHERE false")


def test_kg_role_reads_the_outbox_only(roles):
    with connect(KG) as conn:
        for table in BUSINESS:
            denied(conn, f"SELECT count(*) FROM {table}")
        conn.execute("SELECT count(*) FROM kg_outbox")
        conn.execute("UPDATE kg_outbox SET attempts = attempts WHERE false")
        conn.execute("SELECT count(*) FROM kg_source_versions")
        denied(conn, "INSERT INTO kg_outbox SELECT * FROM kg_outbox WHERE false")
        denied(conn, "SELECT count(*) FROM agent_actions")


async def test_agent_runtime_runs_on_the_agent_role(roles):
    """Một lượt chat có thẻ xác nhận chạy trọn bằng role agent: Store, checkpoint LangGraph, nhật ký thực thi."""
    from uuid import uuid4

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from agentic.agents.workflow import build_workflow
    from agentic.core.app.schemas.request import ChatRequest, ConfirmationRequest
    from agentic.core.context import RequestContext, request_context
    from agentic.services.memory.store import Store
    from agentic.services.runtime import Runtime
    from evaluation.adapters.fixtures import EvalBackend, token_for
    from evaluation.adapters.graph_runtime import ScriptedModels, eval_settings

    meal = [{"name": "Bữa sáng", "consumed_at": "2026-11-02T07:30:00+07:00",
             "items": [{"food": "bánh bao nhân thịt", "quantity": 1, "unit": "SERVING"}]}]
    script = {"decision": [{"intent": "LOG_FOOD", "next_agent": "tool", "domain": "meals", "action": "tool",
                            "instruction": "Ghi bữa ăn.", "meal_log": meal}]}
    dsn = make_conninfo(get_postgres_connection_string(), user=AGENT, password=PASSWORD)
    user_id, session_id, backend = str(uuid4()), uuid4().hex, EvalBackend()
    async with AsyncConnectionPool(dsn, min_size=1, max_size=2, open=False,
                                   kwargs={"autocommit": True, "row_factory": dict_row}) as pool:
        await pool.open(wait=True)
        store, saver, settings = Store(pool, lease_seconds=30, wait_seconds=2), AsyncPostgresSaver(pool), eval_settings()
        await store.ready()
        runtime = Runtime(build_workflow(ScriptedModels(script), store, saver, None, settings), store, saver, settings)
        marker = request_context.set(RequestContext(user_id, token_for(user_id), backend))
        try:
            pending = await runtime.chat(ChatRequest(message="Sáng nay tôi ăn 1 bánh bao nhân thịt",
                                                     session_id=session_id), user_id)
            action = pending.pending_action
            result = await runtime.confirm(ConfirmationRequest(
                session_id=session_id, action_id=action.action_id, revision=action.revision, decision="approve"),
                user_id)
        finally:
            request_context.reset(marker)
    assert result.status == "completed"
    assert [write["tool"] for write in backend.writes] == ["create_meals"]
    with psycopg.connect(get_postgres_connection_string(), autocommit=True) as conn:
        conn.execute("DELETE FROM agent_actions WHERE user_id = %s", (user_id,))
