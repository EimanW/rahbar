# RAHBAR api. Build context: api/   ->   docker build -t rahbar-api:dev api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANONYMIZED_TELEMETRY=False

WORKDIR /app
# dependencies first, so a code change does not reinstall them (layer caching)
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# non-root, numeric so runAsNonRoot can verify it; the manifest makes / read-only
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001

EXPOSE 8000
# exec form: uvicorn is PID 1 and receives SIGTERM directly on a rollout
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
