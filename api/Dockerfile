# RAHBAR api. Build context: api/   ->   docker build -t rahbar-api:dev api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANONYMIZED_TELEMETRY=False

# patch OS packages and the packaging tools themselves (Trivy gate)
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
 && pip install --upgrade pip setuptools wheel

WORKDIR /app
# dependencies first, so a code change does not reinstall them (layer caching)
COPY requirements.txt .
# pip is not needed at runtime: smaller image, one less tool for an attacker
RUN pip install -r requirements.txt && pip uninstall -y pip

COPY app ./app

# non-root, numeric so runAsNonRoot can verify it; the manifest makes / read-only
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001

EXPOSE 8000
# exec form: uvicorn is PID 1 and receives SIGTERM directly on a rollout
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
