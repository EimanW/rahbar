"""Prometheus metrics at /metrics (section 4.8)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

_STAGE_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120)

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
RETRIEVAL_SECONDS = Histogram("rahbar_retrieval_seconds", "Embed + Chroma query time",
                              buckets=_STAGE_BUCKETS)
GENERATION_SECONDS = Histogram("rahbar_generation_seconds", "LLM time incl. one retry",
                               buckets=_STAGE_BUCKETS)
CACHE_LOOKUPS = Counter("rahbar_cache_lookups_total", "Semantic cache lookups", ["result"])
ABSTENTIONS = Counter("rahbar_abstentions_total", "Answers with answered_from_context=false",
                      ["reason"])
FALLBACKS = Counter("rahbar_fallbacks_total", "Canned answers after two invalid replies")
RETRIES = Counter("rahbar_generation_retries_total", "Second attempts after invalid output")
CITATIONS_REMOVED = Counter("rahbar_citations_removed_total",
                            "Model citations dropped because nothing retrieved matched them")
TOKENS = Counter("rahbar_tokens_total", "LLM tokens", ["direction"])
TOKENS_PER_REQUEST = Histogram("rahbar_tokens_per_request", "LLM tokens per request",
                               ["direction"], buckets=(50, 100, 250, 500, 1000, 2000, 4000, 8000))


@router.get("/metrics")
def metrics() -> Response:
    """Cache hit ratio = rahbar_cache_lookups_total{result="hit"} / sum over results."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
