# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install system dependencies required by psycopg and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

# Install uv (pinned) for fast dependency resolution & installation
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

# Install Python dependencies first (cached layer)
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r /app/requirements.txt

# Copy backend source code, owned by the unprivileged runtime user
COPY --chown=app:app . /app
USER app

# =============================================================================
# Target: backend (FastAPI CRUD & OAuth). Production defaults: no reload,
# proxy headers so rate limits see the real client IP behind Caddy.
# Migrations run separately (`alembic upgrade head`, see docker-compose.prod.yml).
# =============================================================================
FROM base AS backend
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8080}/health || exit 1
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "30"]

# =============================================================================
# Target: agentic (LangGraph service). Reload is a development-only override.
# =============================================================================
FROM base AS agentic
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${AGENT_PORT:-8081}/health || exit 1
CMD ["python", "-m", "uvicorn", "agentic.main:app", "--host", "0.0.0.0", "--port", "8081", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "30"]
