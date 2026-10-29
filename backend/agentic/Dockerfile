FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app
EXPOSE 8081
CMD ["python", "-m", "uvicorn", "agentic.core.app.main:app", "--host", "0.0.0.0", "--port", "8081"]
