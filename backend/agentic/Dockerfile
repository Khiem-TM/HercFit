FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY agentic/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY schemas /app/schemas
COPY agentic /app/agentic
COPY knowledge_graph /app/knowledge_graph
EXPOSE 8081
CMD ["python", "-m", "uvicorn", "agentic.main:app", "--host", "0.0.0.0", "--port", "8081"]
