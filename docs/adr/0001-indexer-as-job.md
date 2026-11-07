# ADR 0001: The indexer is a Job; the API only reads

## Status
Accepted · 2026-11-05

## Context
RAHBAR has two workloads with opposite shapes. Indexing (extract, OCR, chunk, embed, store)
runs for minutes, needs a lot of memory, writes to Chroma, and only has to happen when the
documents change. Querying runs on every question, must answer in seconds, and must never
change the index. The api runs as 3 replicas behind one Service, and Chroma has exactly one
volume (a single PVC on `chroma-0`).

Doing the indexing in API startup looks simple and is wrong, because of what 3 replicas do
to it:
1. **Three writers, one volume.** Three pods start together, each halfway through a
   different document, all writing to one collection. The result is an index no single run
   produced, with duplicate or missing chunks.
2. **Every restart re-indexes.** A rolling update, an OOMKill, a node drain or one readiness
   blip pays the full extraction and embedding cost again, and hits the university's site or
   Ollama each time.
3. **Readiness becomes a lie.** Either the pod says ready before the index exists and serves
   empty retrievals, or it takes minutes to become ready, the startup probe kills it, and a
   rolling update swaps three working pods for three that are still chunking PDFs.
4. **No re-index without a redeploy.** Changing the documents would mean restarting the API,
   which is the Lecture 05 "a config change needs a rebuild" failure.

## Decision
- Indexing runs **only** in `indexer/` as a Kubernetes Job (`k8s/base/indexer-job.yaml`:
  `restartPolicy: OnFailure`, `backoffLimit: 3`, `activeDeadlineSeconds: 1800`) and as a weekly
  CronJob with the same image and arguments (`k8s/base/reindex-cronjob.yaml`,
  `concurrencyPolicy: Forbid`, so there is never a second writer).
- The api never writes Chroma. Its readiness probe (`/readyz`, `api/app/routes/health.py`)
  returns 503 until the collection exists, is non-empty, and was built with the same
  `EMBED_MODEL`, so a pod is kept out of the Service until there is something correct to
  retrieve.
- Re-indexing is one command with no redeploy and no downtime:
  `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar` (`make index`).

**What happens to the old index while the api is serving from it?** The indexer builds the
new index in a separate collection, `rahbar-staging`. Only when every chunk is written and the
count matches does it delete `rahbar` and rename staging to `rahbar`
(`indexer/pipeline/store.py`). The api keeps answering from the old index for the whole
build; the swap is two metadata calls. If the Job dies halfway, the live collection is
untouched and the staging leftovers are deleted on the next run. The api fetches the
collection by name on each request (`retrieval/chroma.py`, `_collection`), so it picks up
the new one without a restart. The new `index_version` in the collection metadata also
starts a new semantic-cache namespace, which is how the cache is invalidated (ADR 0003).

## Options considered
- **Index in API startup, guarded by a lock:** fixes (1) but not (2), (3) or (4).
- **An init container on the api:** still runs once per pod start: (2) and (3) remain.
- **A separate indexer Deployment that watches a folder:** a long-running process for a task
  that runs once a week; it also needs its own leader election to stay a single writer.
- **Write straight into the live collection:** simpler, but for the length of the build the
  api would serve a half-built index.

## Consequences
- Easier: the api pods are small, fast to start and stateless; scaling them does not touch
  the index. The index's memory peak is confined to the Job, which has its own limit.
- Harder: someone has to run the Job after a deploy on a fresh cluster (the README apply
  order does). A Job's spec is immutable, so a changed Job manifest must be deleted before it
  is re-applied; routine re-indexing goes through the CronJob template instead.
- Watch: the swap leaves a window of milliseconds in which `rahbar` does not exist. A
  request that lands exactly then gets a 503 from `/api/ask`; readiness needs 3 failures in
  a row (30 s) before it reacts, so pods are not pulled from the Service by the swap.
