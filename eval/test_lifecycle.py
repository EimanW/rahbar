import json
from pipeline.config import get_settings
from pipeline.models import Chunk
from pipeline.incremental import incremental_store
from pipeline.store import get_client

settings = get_settings()
client = get_client(settings)

assert settings.collection == "rahbar-a3-small-test"

def chunk(cid, text, source, version="2026-01", superseded=False):
    return Chunk(
        id=cid,
        text=text,
        source=source,
        section="Policy",
        page=1,
        doc_version=version,
        superseded=superseded
    )

a = chunk("a-001", "Students must attend classes regularly.", "a.txt")
b = chunk("b-001", "Library closes at five.", "b.txt")
changed = chunk("b-001", "Library closes at seven.", "b.txt", "2026-02")

try:
    client.delete_collection(settings.collection)
except Exception:
    pass

print("TEST 1: INITIAL INDEX", flush=True)
incremental_store([a, b], settings)

print("TEST 2: UNCHANGED DOCUMENTS", flush=True)
incremental_store([a, b], settings)

print("TEST 3: CHANGED DOCUMENT", flush=True)
incremental_store([a, changed], settings)

print("TEST 4: DELETED DOCUMENT", flush=True)
incremental_store([a], settings)

collection = client.get_collection(settings.collection)
remaining = collection.get(where={"source": "b.txt"}, include=[])

assert len(remaining["ids"]) == 0
print("DELETED DOCUMENT ORPHAN COUNT: 0", flush=True)

print("TEST 5: RESTORE DOCUMENT", flush=True)
incremental_store([a, b], settings)

collection = client.get_collection(settings.collection)
assert collection.count() == 2

print("RESTORATION: PASS", flush=True)
print("LIFECYCLE TEST COMPLETED", flush=True)

print("TEST 6: SUPERSEDED VERSION", flush=True)

old = chunk("policy-v1", "Library closes at five.", "policy-v1.txt", "2026-01", True)
new = chunk("policy-v2", "Library closes at seven.", "policy-v2.txt", "2026-02", False)

incremental_store([a, old, new], settings)

collection = client.get_collection(settings.collection)

active = collection.get(
    where={"superseded": False},
    include=["metadatas"]
)

assert "policy-v1" not in active["ids"]
assert "policy-v2" in active["ids"]

print("SUPERSEDED VERSION EXCLUDED: PASS", flush=True)

print("TEST 7: VERSION ROLLBACK", flush=True)

old.superseded = False
new.superseded = True

incremental_store([a, old, new], settings)

collection = client.get_collection(settings.collection)

active = collection.get(
    where={"superseded": False},
    include=["metadatas"]
)

assert "policy-v1" in active["ids"]
assert "policy-v2" not in active["ids"]

print("PREVIOUS VERSION RESTORED: PASS", flush=True)
print("ALL SEVEN TESTS COMPLETED", flush=True)
