# Serving image: FastAPI reading precomputed predictions from Postgres.
# The scrape/ingest/predict pipeline runs in GitHub Actions, not here, so
# this image never needs data/raw or model artifacts.
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir .

ENV PORT=8000
# GENPICKS_DATABASE_URL must be provided by the host.
CMD ["sh", "-c", "uvicorn genpicks.api.main:app --host 0.0.0.0 --port ${PORT}"]
