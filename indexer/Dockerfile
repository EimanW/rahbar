# RAHBAR indexer, the Job's image and the only writer to Chroma.
# Build context is the REPOSITORY ROOT, so the image can carry the corpus:
#     docker build -f indexer/Dockerfile -t rahbar-indexer:dev .
# What it carries (docs/PIPELINE.md, "How documents reach the Job"):
#   /fixtures  eval/fixtures, always (the CI corpus)
#   /corpus    corpus/raw/ from `make fetch`, when present on the machine that builds.
#              corpus/raw is gitignored, so images built in CI and pushed to Docker Hub
#              carry the fixtures only: we never republish the university's PDFs.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ANONYMIZED_TELEMETRY=False

# OCR needs system packages, not only pip packages (section 3.1)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY indexer/requirements.txt .
RUN pip install -r requirements.txt

COPY indexer/pipeline ./pipeline
COPY eval/fixtures /fixtures
# the trailing /. copies the folder's contents; an empty corpus/raw/.keep makes this
# work on a fresh clone before anyone has run make fetch
COPY corpus/raw/. /corpus/

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rahbar
USER 10001

# exec form; the Job's args choose --dummy or the real pipeline
ENTRYPOINT ["python", "-m", "pipeline.run"]
