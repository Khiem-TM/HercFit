"""Hạ tầng test tích hợp trên PostgreSQL thật.

Dùng server Postgres của dev nhưng một database riêng (mặc định `hercfit_test`, đặt ở tests/conftest.py). Database được
tạo nếu chưa có và nâng lên `alembic upgrade head` một lần mỗi phiên. Mỗi test tạo user mới; khi test kết thúc các
user đó bị xoá, mọi bảng dữ liệu người dùng có khoá ngoại ON DELETE CASCADE tới `users` nên được dọn theo.
"""
import os
import subprocess
import sys
from datetime import timedelta
from uuid import UUID

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import text

from core.database import get_db_session, get_postgres_connection_string
from core.security import create_access_token
from core.settings import settings

BACKEND = os.path.join(os.path.dirname(__file__), "..", "..", "backend")
# Thứ tự Alembic dựa trên uuid7 nên id tổng hợp vẫn dùng uuid7 cho đúng như dữ liệu thật.
from domains.shared.models.basemodel import uuid7  # noqa: E402

# Chốt an toàn: không bao giờ chạy test tích hợp trên database không kết thúc bằng _test (ví dụ hercfit_db của dev).
if not settings.POSTGRES_DB.endswith("_test"):
    pytest.exit(f"Refusing to run integration tests against database {settings.POSTGRES_DB!r}", returncode=2)


def _ensure_database() -> None:
    target = conninfo_to_dict(get_postgres_connection_string())["dbname"]
    assert target.endswith("_test")
    admin = make_conninfo(get_postgres_connection_string(), dbname="postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone() is None:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ, "POSTGRES_DB": target}, capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def database():
    _ensure_database()


@pytest.fixture(scope="session")
async def app():
    from app import create_app
    return create_app()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
async def make_user():
    """Tạo user hoạt động và trả về (id, header Authorization). Dọn sạch sau test."""
    created: list[UUID] = []

    async def factory(name: str = "Người dùng test", *, lifetime: timedelta | None = None):
        user_id = uuid7()
        async with get_db_session() as session:
            await session.execute(text("INSERT INTO users (id, email, fullname) VALUES (:id, :email, :name)"),
                                  {"id": user_id, "email": f"{user_id}@example.com", "name": name})
        created.append(user_id)
        token = create_access_token({"sub": str(user_id)}, expires_delta=lifetime)
        return user_id, {"Authorization": f"Bearer {token}"}

    yield factory
    if created:
        async with get_db_session() as session:
            await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": created})



@pytest.fixture(scope="session")
async def agent_pool():
    """Pool của agent trên database test; bảng agent và checkpoint LangGraph tạo bằng migrate_pool."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from agentic.migrations.runner import migrate_pool

    async with AsyncConnectionPool(get_postgres_connection_string(), min_size=1, max_size=4, open=False,
                                   kwargs={"autocommit": True, "row_factory": dict_row}) as pool:
        await pool.open(wait=True)
        await migrate_pool(pool, AsyncPostgresSaver(pool))
        yield pool
