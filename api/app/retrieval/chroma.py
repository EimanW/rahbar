"""The real retriever (sections 3.2 and 4.4). Read-only: this process never writes Chroma.

Per question:
  1. embed the question with EMBED_MODEL (api/app/embedding.py), the indexer's model;
  2. query the collection for 4 x k candidates, with a metadata filter that drops
     superseded documents unless the question explicitly asks about an older version;
  3. re-rank the candidates with a small exact-term boost (clause numbers, course
     codes, amounts) because embeddings blur exact terms (corpus property 7);
  4. return the top k as Passages, with score = 1 - cosine distance.

The pin check (4.4) lives in `check_pin`, called by /readyz and at startup.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..config import Settings
from ..embedding import Embedder
from ..schemas import Passage

# "the 2023 rules", "the old policy", "previous handbook", "superseded version". A bare
# "earlier" or "previous" is not enough: "ignore earlier instructions" must not unlock
# repealed clauses, so those words only count next to a document noun.
_DOC = r"(?:version|edition|rules?|handbook|policy|prospectus|regulations?|revision)"
_OLDER = re.compile(rf"\b(?:(?:old|older|previous|earlier|former|outdated|prior|last year'?s)"
                    rf"\s+(?:\w+\s+)?{_DOC}|superseded|repealed|(?:before|until) the "
                    rf"(?:revision|update|change)|20(?:1\d|2[0-5])(?:-\d{{2}})?\s+{_DOC}|"
                    rf"{_DOC}\s+(?:of|from|in)\s+20(?:1\d|2[0-5]))\b", re.I)
# clause numbers (1.21, 5.4), course codes (CS4032), amounts and percentages
_EXACT = re.compile(r"\b(?:[A-Z]{2,4}[- ]?\d{3,4}|\d+\.\d+|\d{1,3}(?:,\d{3})+|\d+%?)\b")
EXACT_BOOST = 0.05
META_TTL_SECONDS = 15.0


def wants_older_version(question: str) -> bool:
    return bool(_OLDER.search(question))


def exact_terms(text: str) -> set[str]:
    return {t.lower() for t in _EXACT.findall(text)}


class PinMismatch(RuntimeError):
    """The collection was built with a different embedding model or dimension."""


class ChromaRetriever:
    name = "chroma"

    def __init__(self, settings: Settings, client: Any | None = None,
                 embedder: Embedder | None = None) -> None:
        self.settings = settings
        if client is None:
            import chromadb  # the thin client, from chromadb-client in requirements.txt
            from chromadb.config import Settings as ChromaSettings

            client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                                         settings=ChromaSettings(anonymized_telemetry=False))
        self.client = client
        self.embedder = embedder or Embedder(settings)
        self._meta: dict[str, Any] = {}
        self._meta_at = 0.0

    # -- collection state ---------------------------------------------------------
    def _collection(self) -> Any:
        # fetched per call, not cached: the indexer swaps in a new collection (ADR 0001)
        return self.client.get_collection(self.settings.collection)

    def collection_info(self) -> dict[str, Any]:
        """Metadata plus count, cached for a few seconds. Raises if Chroma is unreachable
        or the collection does not exist."""
        now = time.monotonic()
        if not self._meta or now - self._meta_at > META_TTL_SECONDS:
            col = self._collection()
            self._meta = {**(col.metadata or {}), "count": int(col.count())}
            self._meta_at = now
        return self._meta

    def count(self) -> int:
        return int(self.collection_info()["count"])

    def index_version(self) -> str:
        return str(self.collection_info().get("index_version", "unknown"))

    def check_pin(self, query_dim: int | None = None) -> None:
        """Raise PinMismatch, naming both sides, when the index and this API disagree."""
        info = self.collection_info()
        built_with = info.get("embed_model")
        if built_with != self.settings.embed_model:
            raise PinMismatch(f"embedding model mismatch: index built with {built_with!r}, "
                              f"api EMBED_MODEL={self.settings.embed_model!r}")
        if query_dim is not None and info.get("dimension") not in (None, query_dim):
            raise PinMismatch(f"embedding dimension mismatch: index {info.get('dimension')}, "
                              f"api produces {query_dim}")

    # -- query ----------------------------------------------------------------------
    def embed(self, text: str) -> list[float]:
        return self.embedder.embed(text)

    def retrieve(self, question: str, k: int, vector: list[float] | None = None) -> list[Passage]:
        vector = vector or self.embed(question)
        self.check_pin(len(vector))
        keep_old = wants_older_version(question) or not self.settings.filter_superseded
        where = None if keep_old else {"superseded": False}
        result = self._collection().query(
            query_embeddings=[vector], n_results=max(k * 4, k), where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        docs = result["documents"][0]
        metas = result["metadatas"][0]
        dists = result["distances"][0]
        wanted = exact_terms(question)
        scored = []
        for cid, text, meta, dist in zip(ids, docs, metas, dists):
            similarity = 1.0 - float(dist)
            boost = EXACT_BOOST * len(wanted & exact_terms(text)) if wanted else 0.0
            scored.append((similarity + boost, Passage(
                chunk_id=cid, text=text, source=str(meta.get("source", "?")),
                section=str(meta.get("section", "?")),
                page=int(meta["page"]) if meta.get("page") is not None else None,
                score=round(similarity, 4), superseded=bool(meta.get("superseded", False)),
            )))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [p for _, p in scored[:k]]
