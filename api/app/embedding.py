"""Query embedding, with the same model and the same rules the indexer used.

The pin (section 4.4): EMBED_MODEL is read from the same ConfigMap key as the indexer,
and api/app/retrieval/chroma.py refuses to serve when the collection was built with a
different model or dimension.
"""

from __future__ import annotations

import httpx

from .config import Settings
from .hashembed import hash_dimension, hash_embed, is_hash_model


def query_prefix(model: str) -> str:
    # nomic-embed-text is trained with task prefixes; the indexer uses "search_document: "
    return "search_query: " if model.startswith("nomic-embed-text") else ""


class Embedder:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.embed_model
        self.url = settings.ollama_url.rstrip("/")
        self._client = None if is_hash_model(self.model) else httpx.Client(
            timeout=httpx.Timeout(30.0, connect=5.0))

    def embed(self, text: str) -> list[float]:
        if is_hash_model(self.model):
            return hash_embed(text, hash_dimension(self.model))
        assert self._client is not None
        response = self._client.post(f"{self.url}/api/embed",
                                     json={"model": self.model,
                                           "input": [query_prefix(self.model) + text]})
        response.raise_for_status()
        return list(response.json()["embeddings"][0])
