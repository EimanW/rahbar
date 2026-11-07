# ADR 0003: The semantic cache lives in Redis, namespaced by index version

## Status
Accepted · 2026-11-05

## Context
Students ask the same things in different words ("What CGPA puts me on warning?" /
"minimum CGPA to avoid academic warning"). Each miss costs an embedding call, a Chroma query
and seconds of a 3B model on a laptop. Section 3.3 allows Redis or a second Chroma collection,
and requires: a cosine threshold from the ConfigMap, chosen with data; never caching follow-ups,
abstentions, out-of-scope answers or failed validations; invalidation on re-index.

## Decision
- **Redis** (`k8s/base/redis.yaml`: Deployment + PVC, append-only file, `maxmemory 200mb`
  with LRU eviction), reached only by the api (NetworkPolicy `redis-from-api`).
- Layout (`api/app/services/cache.py`): one hash per `(index_version, embed_model)`, field =
  entry id, value = `{question, vector, response}`. A lookup scans the current namespace and
  takes the best cosine; a hit needs `cosine >= CACHE_THRESHOLD`.
- **Invalidation on re-index:** the namespace contains the `index_version` the indexer writes
  into the collection metadata. A new index means a new, empty namespace; the old hash expires
  (TTL). Nothing has to remember to flush.
- **Never cached** (`is_cacheable`): follow-ups (`is_followup`), abstentions, fallbacks, and any
  answer whose citations failed the retrieved-chunk check.
- A Redis outage degrades to "no cache"; it never fails a request. `/readyz` still reports it.

## Options considered
- **Second Chroma collection:** a real vector index, so lookups are sub-linear; but it puts a
  write path from the api into Chroma, which ADR 0001 keeps read-only for the api, and it would
  need the indexer to delete the cache collection on re-index, a second writer's job.
- **Exact-match cache (hash of the normalised question):** never wrong, but misses every
  rephrasing; the main win of caching disappears.
- **No cache:** simplest; every repeat question pays full latency.

## Consequences
- Easier: invalidation is automatic and the api stays the only cache writer.
- Harder: the lookup is a linear scan over the namespace, fine for hundreds of entries.
  At thousands we would move to RediSearch vector search (`FT.SEARCH ... KNN`).
- Watch: `rahbar_cache_lookups_total{result="hit"}` against misses gives the hit ratio; a high
  hit ratio with rising complaints means the threshold is too low (false hits).
