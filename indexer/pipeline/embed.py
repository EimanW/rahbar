"""Stage 4: Embed. One vector per chunk, from the pinned model only.

EMBED_MODEL comes from the ConfigMap the API also reads (section 4.4).
- "nomic-embed-text" (prod): Ollama POST {OLLAMA_URL}/api/embed, batched.
  nomic-embed-text is trained with task prefixes, so documents get "search_document: "
  and the API's queries get "search_query: ". Both sides use the same rule.
- "hash-bow-<dim>" (CI only): the lexical embedder in hashembed.py, no network.
"""

from __future__ import annotations

import httpx

from .config import IndexerSettings
from .hashembed import hash_dimension, hash_embed, is_hash_model

BATCH = 32
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def document_prefix(model: str) -> str:
    return "search_document: " if model.startswith("nomic-embed-text") else ""


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    model = settings.embed_model
    if is_hash_model(model):
        dim = hash_dimension(model)
        return [hash_embed(t, dim) for t in texts]
    prefix = document_prefix(model)
    vectors: list[list[float]] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for start in range(0, len(texts), BATCH):
            batch = [prefix + t for t in texts[start:start + BATCH]]
            response = client.post(f"{settings.ollama_url.rstrip('/')}/api/embed",
                                   json={"model": model, "input": batch})
            response.raise_for_status()
            got = response.json()["embeddings"]
            if len(got) != len(batch):
                raise RuntimeError(f"asked for {len(batch)} embeddings, got {len(got)}")
            vectors.extend(got)
    dims = {len(v) for v in vectors}
    if len(dims) > 1:
        raise RuntimeError(f"embedding model {model} returned mixed dimensions {sorted(dims)}")
    return vectors
