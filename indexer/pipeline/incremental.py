import hashlib
import json
import time

from .embed import embed
from .store import get_client, WRITE_BATCH


def incremental_store(chunks, settings):
    client = get_client(settings)
    live = settings.collection
    staging = live + "-staging"

    previous = {}
    old_sources = {}

    try:
        old = client.get_collection(live)
    except Exception:
        old = None

    if old is not None:
        for offset in range(0, old.count(), WRITE_BATCH):
            data = old.get(
                limit=WRITE_BATCH,
                offset=offset,
                include=["documents", "embeddings", "metadatas"]
            )

            for i, cid in enumerate(data["ids"]):
                meta = data["metadatas"][i]
                source = meta["source"]
                old_sources.setdefault(source, []).append(cid)

                previous[cid] = (
                    data["documents"][i],
                    data["embeddings"][i].tolist(),
                    meta
                )

    grouped = {}

    for c in chunks:
        grouped.setdefault(c.source, []).append(c)

    stats = []
    vectors = {}

    compatible = (
        old is not None
        and (old.metadata or {}).get("embed_model") == settings.embed_model
    )

    for source, pieces in grouped.items():
        unchanged = (
            compatible
            and set(old_sources.get(source, [])) == {c.id for c in pieces}
            and all(
                previous[c.id][0] == c.text
                and previous[c.id][2] == c.metadata()
                for c in pieces
            )
        )

        if unchanged:
            for c in pieces:
                vectors[c.id] = previous[c.id][1]
        else:
            new_vectors = embed([c.text for c in pieces], settings)
            for c, vector in zip(pieces, new_vectors):
                vectors[c.id] = vector

        stats.append({
            "doc_id": source,
            "status": "unchanged" if unchanged else (
                "changed" if source in old_sources else "new"
            ),
            "chunks": len(pieces),
            "embedded_chunks": 0 if unchanged else len(pieces)
        })

    deleted = set(old_sources) - set(grouped)

    for source in sorted(deleted):
        stats.append({
            "doc_id": source,
            "status": "deleted",
            "removed_chunks": len(old_sources[source]),
            "embedded_chunks": 0
        })

    if not chunks:
        raise ValueError("Refusing to replace index with empty collection")

    try:
        client.delete_collection(staging)
    except Exception:
        pass

    target = client.create_collection(
        name=staging,
        metadata={
            "hnsw:space": "cosine",
            "embed_model": settings.embed_model,
            "dimension": len(vectors[chunks[0].id]),
            "index_version": str(time.time_ns()),
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap
        }
    )

    for start in range(0, len(chunks), WRITE_BATCH):
        part = chunks[start:start + WRITE_BATCH]

        target.add(
            ids=[c.id for c in part],
            documents=[c.text for c in part],
            embeddings=[vectors[c.id] for c in part],
            metadatas=[c.metadata() for c in part]
        )

    if target.count() != len(chunks):
        raise RuntimeError("Staging collection count mismatch")

    for source in deleted:
        remaining = target.get(
            where={"source": source},
            include=[]
        )
        if remaining["ids"]:
            raise RuntimeError("Orphan chunks: " + source)

    if old is not None:
        client.delete_collection(live)

    target.modify(name=live)

    for row in stats:
        print(json.dumps({
            "event": "incremental_document",
            **row
        }), flush=True)

    print(json.dumps({
        "event": "incremental_summary",
        "embedded_chunks": sum(
            r["embedded_chunks"] for r in stats
        ),
        "total_chunks": len(chunks),
        "unchanged_documents": sum(
            r["status"] == "unchanged" for r in stats
        ),
        "deleted_documents": len(deleted),
        "orphan_chunks": 0
    }), flush=True)

    return len(chunks)
