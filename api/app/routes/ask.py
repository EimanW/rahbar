"""POST /api/ask. The Ingress sends /api/* here unchanged, so the prefix stays."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..schemas import AskRequest, AskResponse
from ..services.answer import answer_question

router = APIRouter(prefix="/api")
log = logging.getLogger("rahbar.ask")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    state = request.app.state
    try:
        return answer_question(body.question, state.retriever, state.provider, state.settings,
                               cache=getattr(state, "cache", None))
    except Exception as exc:
        # The index is unusable (Chroma down, collection missing, embedding pin broken).
        # Readiness already keeps this pod out of the Service; a direct caller still gets
        # an honest 503 with the reason, never a 500 stack trace.
        from ..retrieval.chroma import PinMismatch

        reason = str(exc) if isinstance(exc, PinMismatch) else f"retrieval unavailable: {type(exc).__name__}"
        log.error("ask failed", extra={"reason": reason})
        raise HTTPException(status_code=503, detail=reason) from exc
