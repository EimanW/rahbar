"""Turns a question into an AskResponse. The query pipeline of section 3.2:

  1. receive and validate        (routes/ask.py, AskRequest: 3 to 500 characters)
  2. semantic cache check        (services/cache.py; skipped for follow-ups)
  3. embed with the pinned model (retriever.embed)
  4. retrieve top_k, superseded documents filtered out (retrieval/chroma.py)
     + relevance floor: if nothing clears RELEVANCE_FLOOR, abstain without calling the LLM
  5. augment                     (services/generation.py)
  6. generate, schema-constrained, at TEMPERATURE from the ConfigMap
  7. validate, retry once, fall back; then drop any citation that was not retrieved
  8. store a cache entry, only when it is safe to cache
One JSON log line per request records top_k, chunk ids, scores and whether it abstained.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..retrieval.base import Retriever
from ..routes import metrics as m
from ..schemas import AskResponse, Citation, Passage, RetrievedRef
from .cache import SemanticCache, is_cacheable, is_followup
from .citations import filter_citations
from .generation import generate

log = logging.getLogger("rahbar.answer")

NOT_COVERED = ("The documents I have do not cover this question, so I can't answer it "
               "reliably. Try the relevant office or the official FAST-NUCES website.")
UNSUPPORTED = ("I found related passages, but none of them supports a definite answer, "
               "so I won't guess.")


def _refs(passages: list[Passage]) -> list[RetrievedRef]:
    return [RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section, page=p.page,
                         score=p.score, superseded=p.superseded) for p in passages]


def answer_question(question: str, retriever: Retriever, provider: LLMProvider,
                    settings: Settings, cache: SemanticCache | None = None) -> AskResponse:
    rid = request_id_var.get()
    followup = is_followup(question)

    # 2-3. embed once; the same vector serves the cache and retrieval
    started = time.perf_counter()
    vector = retriever.embed(question)
    namespace = None
    if cache is not None and not followup:
        namespace = cache.namespace(retriever.index_version(), settings.embed_model)
        try:
            hit, similarity = cache.lookup(namespace, vector)
        except Exception as exc:          # a cache outage must not take answers down
            log.warning("cache lookup failed", extra={"error": str(exc)})
            hit, similarity = None, 0.0
        m.CACHE_LOOKUPS.labels(result="hit" if hit else "miss").inc()
        if hit:
            log.info("answered", extra={"cache": "hit", "similarity": round(similarity, 4),
                                        "answered_from_context": hit["answered_from_context"]})
            return AskResponse(**{**hit, "request_id": rid, "cached": True})
    elif cache is not None:
        m.CACHE_LOOKUPS.labels(result="skipped_followup").inc()

    # 4. retrieve, then the relevance floor
    passages = retriever.retrieve(question, k=settings.top_k, vector=vector)
    m.RETRIEVAL_SECONDS.observe(time.perf_counter() - started)
    best = max((p.score for p in passages), default=0.0)
    relevant = [p for p in passages if p.score >= settings.relevance_floor]

    fallback = retried = False
    removed = 0
    citations: list[Citation]
    confidence: Literal["high", "medium", "low"]
    tokens_in = tokens_out = 0
    if not relevant:
        abstain_reason = "below_floor"
        answer_text, citations, from_context, confidence = NOT_COVERED, [], False, "low"
    else:
        # 5-7. augment, generate, validate (retry + fallback inside generate)
        g_started = time.perf_counter()
        result = generate(provider, question, relevant, settings.temperature)
        m.GENERATION_SECONDS.observe(time.perf_counter() - g_started)
        fallback, retried = result.fallback, result.retried
        tokens_in, tokens_out = result.tokens_in, result.tokens_out
        ans = result.answer
        citations, removed = filter_citations(ans.citations, relevant)
        from_context, confidence, answer_text = ans.answered_from_context, ans.confidence, ans.answer
        abstain_reason = "fallback" if fallback else ("model_declined" if not from_context else "")
        if from_context and not citations:
            # claimed an answer but cited nothing we retrieved: unsupported, so abstain
            from_context, confidence, answer_text = False, "low", UNSUPPORTED
            abstain_reason = "no_valid_citation"
        if not from_context:
            citations = []

    if not from_context:
        m.ABSTENTIONS.labels(reason=abstain_reason).inc()
    if fallback:
        m.FALLBACKS.inc()
    if retried:
        m.RETRIES.inc()
    if removed:
        m.CITATIONS_REMOVED.inc(removed)
    m.TOKENS.labels(direction="in").inc(tokens_in)
    m.TOKENS.labels(direction="out").inc(tokens_out)
    m.TOKENS_PER_REQUEST.labels(direction="in").observe(tokens_in)
    m.TOKENS_PER_REQUEST.labels(direction="out").observe(tokens_out)

    response = AskResponse(
        request_id=rid, answer=answer_text, citations=citations,
        answered_from_context=from_context, confidence=confidence,
        retrieved=_refs(passages), provider=provider.name,
    )
    log.info("answered", extra={
        "cache": "miss" if namespace else "off", "followup": followup,
        "retriever": retriever.name, "provider": provider.name, "top_k": settings.top_k,
        "chunk_ids": [p.chunk_id for p in passages],
        "scores": [round(p.score, 4) for p in passages], "best_score": round(best, 4),
        "relevance_floor": settings.relevance_floor,
        "answered_from_context": from_context, "abstain_reason": abstain_reason or None,
        "citations_removed": removed, "retried": retried, "fallback": fallback,
        "tokens_in": tokens_in, "tokens_out": tokens_out,
    })

    # 8. store, only when safe
    if cache is not None and namespace is not None:
        body = response.model_dump(exclude={"request_id", "cached"})
        if is_cacheable(question, body, fallback, citations_ok=removed == 0):
            try:
                cache.store(namespace, question, vector, body)
            except Exception as exc:
                log.warning("cache store failed", extra={"error": str(exc)})
    return response
