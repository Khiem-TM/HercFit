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
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution & installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Python dependencies first (cached layer)
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r /app/requirements.txt

# Copy backend source code
COPY . /app

# =============================================================================
# Target: streamlit (Optional Streamlit Chat / Debug UI)
# =============================================================================
FROM base AS streamlit
EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]

# =============================================================================
# Target: backend (Default FastAPI CRUD & OAuth Service)
# =============================================================================
FROM base AS backend
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8080}/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && python run_service.py"]

# =============================================================================
# Target: agentic (LangGraph Multi-Agent Service)
# =============================================================================
FROM base AS agentic
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${AGENT_PORT:-8081}/health || exit 1

CMD ["python", "-m", "uvicorn", "agentic.main:app", "--host", "0.0.0.0", "--port", "8081", "--reload"]

