# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.6.0" \
    "python-dotenv>=1.0.1" \
    "httpx>=0.27.2" \
    "langchain-core>=0.3.25" \
    "langgraph>=0.2.60" \
    "langgraph-checkpoint-postgres>=2.0.9" \
    "langsmith>=0.2.3" \
    "langchain-openai>=0.2.12" \
    "psycopg[binary,pool]>=3.2.3" \
    "psycopg-pool>=3.2.4"

EXPOSE 8081

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:${AGENT_PORT:-8081}/health || exit 1

CMD ["python", "main.py"]

