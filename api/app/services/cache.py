"""Semantic cache in Redis (section 3.3, ADR 0003).

Layout: one Redis hash per (index_version, embed_model):
    rahbar:cache:<index_version>:<embed_model>  field = entry id, value = JSON
    {"q": question, "v": [vector], "r": AskResponse dict}
A lookup reads every entry of the current namespace and takes the best cosine. That is a
linear scan: fine for a coursework-sized cache (hundreds of entries), and the reason
ADR 0003 names a vector index (RediSearch / a second Chroma collection) as the next step.

Invalidation on re-index: the namespace contains the index_version the indexer wrote into
the collection metadata. A new index means a new namespace, so old answers are never
served from it; the old hash simply expires (TTL).

Never cached (`is_cacheable`): follow-up questions, abstentions, out-of-scope answers,
fallbacks, and answers whose citations failed the check.
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from typing import Any

log = logging.getLogger("rahbar.cache")

_FOLLOWUP = re.compile(
    r"^\s*(and|but|also|what about|how about|same for|it|its|that one|those|they|them|"
    r"tell me more|explain (that|it|more))\b"
    r"|\b(about|of|for|with|on) (it|that|this|those|these|them)\s*\??\s*$", re.I)


def is_followup(question: str) -> bool:
    """A question that only makes sense after an earlier turn. Never cached: 'and the
    fee for that?' means something different in every conversation."""
    return bool(_FOLLOWUP.search(question))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    def __init__(self, client: Any, threshold: float, ttl_seconds: int) -> None:
        self.client = client
        self.threshold = threshold
        self.ttl = ttl_seconds

    @staticmethod
    def namespace(index_version: str, embed_model: str) -> str:
        return f"rahbar:cache:{index_version}:{embed_model}"

    def ping(self) -> bool:
        return bool(self.client.ping())

    def lookup(self, ns: str, vector: list[float]) -> tuple[dict | None, float]:
        best, best_sim = None, 0.0
        for raw in self.client.hvals(ns):
            entry = json.loads(raw)
            sim = cosine(vector, entry["v"])
            if sim > best_sim:
                best, best_sim = entry, sim
        if best is not None and best_sim >= self.threshold:
            return best["r"], best_sim
        return None, best_sim

    def store(self, ns: str, question: str, vector: list[float], response: dict) -> None:
        self.client.hset(ns, uuid.uuid4().hex, json.dumps({"q": question, "v": vector,
                                                           "r": response}))
        self.client.expire(ns, self.ttl)


def is_cacheable(question: str, response: dict, fallback: bool, citations_ok: bool) -> bool:
    return (not is_followup(question) and not fallback and citations_ok
            and bool(response.get("answered_from_context")) and bool(response.get("citations")))


def make_cache(host: str, port: int, threshold: float, ttl_seconds: int) -> SemanticCache | None:
    if not host:
        return None
    import redis

    client = redis.Redis(host=host, port=port, socket_timeout=2.0, socket_connect_timeout=2.0)
    return SemanticCache(client, threshold, ttl_seconds)
