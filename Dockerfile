FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY pyproject.toml .

# --- API service ---
FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "src.ingestion.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Worker service ---
FROM base AS worker
CMD ["python", "-m", "src.ingestion.workers.runner", "all"]

# --- Migration runner ---
FROM base AS migrate
CMD ["alembic", "upgrade", "head"]
