"""HercFit CRUD application; independent of Agent providers and memory stores."""

from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from core.database import get_async_engine, close_crud_db_pool
from core.settings import settings
from routers import api_router
from services.common import request_validation_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.jwt_secret_value  # Authentication must be configured even without an AI provider.
    get_async_engine()
    try:
        yield
    finally:
        await close_crud_db_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="HercFit Backend", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"], expose_headers=["Location"],
    )
    app.include_router(api_router, prefix="/api")

    @app.exception_handler(ValidationError)
    async def domain_validation(request: Request, exc: ValidationError):
        return await request_validation_exception_handler(request, request_validation_error(exc, "body"))

    @app.exception_handler(StaleDataError)
    async def stale_version(_request: Request, _exc: StaleDataError):
        return JSONResponse(status_code=409, content={"detail": "Version has changed; reload before editing"})

    @app.exception_handler(IntegrityError)
    @app.exception_handler(DataError)
    async def database_constraint(_request: Request, exc):
        code = getattr(exc.orig, "sqlstate", None)
        if code in {"23505", "23503"}:
            return JSONResponse(status_code=409, content={"detail": "Data conflicts with an existing record"})
        if code in {"23514", "23502", "22003", "22001"}:
            return JSONResponse(status_code=422, content={"detail": "Data violates a storage constraint"})
        return JSONResponse(status_code=500, content={"detail": "Database operation failed"})

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())

    @app.get("/health/ready", tags=["health"], responses={503: {"description": "Database or schema is not ready"}})
    async def ready():
        try:
            async with get_async_engine().connect() as connection:
                revisions = set((await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            if revisions == expected_heads or "0001_initial_schema" in revisions or "0003_plans_and_journals" in revisions:
                return {"status": "ready"}
        except (SQLAlchemyError, OSError):
            pass
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    return app


app = create_app()
