"""Stage 5: Store. The only code in the whole system that writes to Chroma.

What happens to the old index while the API serves from it (ADR 0001):
the new index is built in a separate staging collection. Only when every chunk is
written does the indexer delete the live collection and rename staging to the live
name. The API keeps answering from the old index during the whole (minutes-long)
build; the swap itself is two metadata calls. If the Job dies halfway, the live
collection is untouched and the half-built staging one is deleted on the next run.

The collection metadata records the pin (section 4.4): embed_model and dimension,
plus index_version, which the API uses to invalidate its semantic cache (section 3.3).
"""

from __future__ import annotations

import time
from typing import Any

from .config import IndexerSettings
from .models import Chunk

WRITE_BATCH = 256


def get_client(settings: IndexerSettings) -> Any:
    import chromadb  # the thin client, from chromadb-client in requirements.txt
    from chromadb.config import Settings as ChromaSettings

    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port,
                               settings=ChromaSettings(anonymized_telemetry=False))


def store(chunks: list[Chunk], vectors: list[list[float]], settings: IndexerSettings,
          client: Any | None = None) -> int:
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    if not chunks:
        raise ValueError("refusing to replace the index with an empty one")
    ids = [c.id for c in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate chunk ids; ids must be unique per document position")
    dimension = len(vectors[0])
    client = client or get_client(settings)
    live, staging = settings.collection, f"{settings.collection}-staging"

    try:
        client.delete_collection(staging)        # leftovers from a failed run
    except Exception:
        pass
    collection = client.create_collection(
        name=staging,
        metadata={
            "hnsw:space": "cosine",
            "embed_model": settings.embed_model,
            "dimension": dimension,
            "index_version": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
        },
    )
    for start in range(0, len(chunks), WRITE_BATCH):
        part = chunks[start:start + WRITE_BATCH]
        collection.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            embeddings=vectors[start:start + WRITE_BATCH],
            metadatas=[c.metadata() for c in part],
        )
    count = int(collection.count())
    if count != len(chunks):
        raise RuntimeError(f"wrote {len(chunks)} chunks but staging holds {count}")

    try:
        client.delete_collection(live)
    except Exception:                            # first run: no live collection yet
        pass
    collection.modify(name=live)
    return count
