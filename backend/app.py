"""Ứng dụng CRUD của HercFit; không phụ thuộc nhà cung cấp Agent hay kho bộ nhớ."""

import asyncio
from contextlib import asynccontextmanager, suppress
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
from agentic.observability import observer
from agentic.observability.middleware import ObservabilityMiddleware
from core.media_limits import ImageUploadLimit
from core.route_metrics import RouteMetricsMiddleware
from api.v1 import api_router
from api.v2 import api_v2_router
from domains.shared.services.common import request_validation_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.jwt_secret_value  # Xác thực phải được cấu hình kể cả khi không có nhà cung cấp AI.
    get_async_engine()
    observer()
    from agentic.embedding.core import EmbeddingClient, RerankClient, settings as embedding_settings
    app.state.embedding_client = app.state.rerank_client = None
    if embedding_settings().RAG_ENABLED:
        try:
            app.state.embedding_client = EmbeddingClient(embedding_settings())
            if embedding_settings().RERANK_ENABLED:
                app.state.rerank_client = RerankClient(embedding_settings())
        except ValueError:
            pass  # Cấu hình RAG tuỳ chọn không thể tắt CRUD/chat.
    cleanup_task = None
    if all((settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET)):
        from domains.media.services.image_cleanup import cleanup_loop
        cleanup_task = asyncio.create_task(cleanup_loop())
    health_task = None
    if settings.google_health_configured and settings.GOOGLE_HEALTH_SYNC_LOOP:
        from integrations.google_health.scheduler import health_sync_loop
        health_task = asyncio.create_task(health_sync_loop())
    briefing_task = None
    if settings.DAILY_BRIEFING_LOOP:
        from domains.notifications.services.loop import daily_briefing_loop
        briefing_task = asyncio.create_task(daily_briefing_loop())
    metrics_stop, metrics_task = asyncio.Event(), None
    if settings.API_ROUTE_METRICS:
        from core.database import get_db_session
        from core.route_metrics import flush_loop
        app.openapi()  # dựng (và cache) schema mà bảng route đọc, trước request đầu tiên
        metrics_task = asyncio.create_task(flush_loop(metrics_stop, get_db_session))
    try:
        yield
    finally:
        if metrics_task is not None:
            metrics_stop.set()  # flush lần cuối trước khi đóng pool
            with suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(metrics_task, 5)
        for task in (cleanup_task, health_task, briefing_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        for client in (app.state.embedding_client, app.state.rerank_client):
            if client is not None:
                await client.close()
        await observer().close()
        await close_crud_db_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="HercFit Backend", version="1.0.0", lifespan=lifespan)
    app.add_middleware(ImageUploadLimit)
    app.add_middleware(ObservabilityMiddleware, service='backend', accept_parent=True)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"], expose_headers=["Location", "X-Request-ID", "X-Trace-ID"],
    )
    # Lớp ngoài cùng: số đếm và độ trễ theo route cho mọi request /api (core/route_metrics.py).
    app.add_middleware(RouteMetricsMiddleware)
    app.include_router(api_v2_router, prefix="/api/v2")
    app.include_router(api_router, prefix="/api")
    from agentic.embedding.retrieval.router import router as embedding_router
    app.include_router(embedding_router, prefix="/api")

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
            if revisions == expected_heads:
                return {"status": "ready", "observability": observer().status(), "rag": "configured" if getattr(app.state,"embedding_client",None) else "disabled_or_unavailable", "rerank": "configured" if getattr(app.state,"rerank_client",None) else "disabled"}
        except (SQLAlchemyError, OSError):
            pass
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    return app


app = create_app()
