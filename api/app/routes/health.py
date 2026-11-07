"""Liveness and readiness (section 4.3). They answer different questions.

/healthz: is the process alive? It touches nothing, so a slow Chroma can never make the
kubelet restart every replica at once (the restart storm).
/readyz: can this pod answer a question right now? 200 only when Chroma is reachable,
the collection exists and is non-empty, its embedding model matches EMBED_MODEL, and
Redis is reachable. Otherwise 503, naming the dependency that failed, so the pod is
taken out of the Service until there is something correct to retrieve.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response

router = APIRouter()
log = logging.getLogger("rahbar.ready")
_last_logged: dict[str, str] = {}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


def readiness_report(state: Any, log_mismatch: bool = False) -> dict[str, str]:
    """One entry per dependency: "ok" or the reason it failed."""
    checks: dict[str, str] = {}
    retriever = state.retriever
    if retriever.name == "chroma":
        from ..retrieval.chroma import PinMismatch

        try:
            info = retriever.collection_info()
            count = retriever.count()
            checks["chroma"] = "ok"
            checks["collection"] = "ok" if count > 0 else "collection is empty"
            try:
                retriever.check_pin()
                checks["embed_model"] = "ok"
            except PinMismatch as exc:
                checks["embed_model"] = str(exc)
                if log_mismatch or _last_logged.get("pin") != str(exc):
                    log.error("refusing to become ready", extra={
                        "reason": str(exc), "index_embed_model": info.get("embed_model"),
                        "api_embed_model": state.settings.embed_model})
                    _last_logged["pin"] = str(exc)
        except Exception as exc:  # unreachable, or the collection does not exist yet
            checks["chroma"] = f"unavailable: {type(exc).__name__}: {str(exc)[:120]}"
    cache = getattr(state, "cache", None)
    if cache is not None:
        try:
            checks["redis"] = "ok" if cache.ping() else "redis did not answer PING"
        except Exception as exc:
            checks["redis"] = f"unavailable: {type(exc).__name__}"
    return checks


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    checks = readiness_report(request.app.state)
    failed = {k: v for k, v in checks.items() if v != "ok"}
    if failed:
        response.status_code = 503
        return {"status": "not ready", "failed": failed, "checks": checks}
    return {"status": "ready", "checks": checks}
