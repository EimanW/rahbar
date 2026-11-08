# Engineering notes

Line numbers refer to the files as committed. Where an answer needs a number that only the
running cluster can give (`kubectl top`, real-corpus recall), it was measured on minikube on
8 Nov 2026 and cites the file it came from; nothing here is a guess dressed up as a measurement.

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?
Three pods would start at once (`k8s/base/api.yaml:9`, `replicas: 3`) and each would begin
writing the same collection on the single Chroma PVC (`k8s/base/chroma-statefulset.yaml:64`,
`volumeClaimTemplates`, one replica at line 13). **The failure is three concurrent writers**: each
pod is halfway through a different document, our store stage deletes and recreates the
collection (`indexer/pipeline/store.py:47-52`), so one pod's delete wipes another's half-written
staging data, and what survives is an index no single run produced. On top of that, every
rolling update, OOMKill or node drain re-runs the full extraction and embedding, and readiness
can no longer be honest: the pod is either ready before the index exists or so slow to start
that its startup probe (`api.yaml:52-55`, 30 x 2 s = 60 s budget) kills it.

**The object that prevents it is the Job**, `k8s/base/indexer-job.yaml:5` (`kind: Job`,
`restartPolicy: OnFailure` at line 18, `backoffLimit: 3` at line 11), plus the CronJob with
`concurrencyPolicy: Forbid` for re-indexing, so there is only ever one writer. The api process
has no write path at all: `api/app/retrieval/chroma.py` only calls `get_collection`, `count` and
`query`. Reasoning in full: `docs/adr/0001-indexer-as-job.md`.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?
Today readiness (`/readyz`, `api.yaml:60-63`) depends on Chroma and liveness (`/healthz`,
`api.yaml:56-59`) touches nothing (`api/app/routes/health.py:24`). If Chroma is slow for 90 s,
`/readyz` fails, each pod is removed from the Service endpoints after 3 failed checks
(3 x 10 s), nothing is restarted, and as soon as Chroma answers the pods return to the Service.
Users see 503s or slow answers for about 90 s, then recovery with no restarts.

**Swapped**, the liveness probe would call Chroma: after 3 failures x 20 s = 60 s the kubelet
kills the container in **all three replicas at once**, because they all depend on the same slow
Chroma. They restart, the startup probe passes (`/healthz` would now be the cheap one), liveness
hits slow Chroma again, and they are killed again: CrashLoopBackOff with growing back-off. When
Chroma recovers at 90 s, the pods are still waiting out their back-off, so the outage lasts
longer than Chroma's slowness. Meanwhile the swapped readiness probe checks nothing, so a pod
that is up is considered ready even if Chroma is down. What was merely slow becomes down: the
restart storm. That is why liveness must never touch a dependency.

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?
The HPA (`k8s/base/hpa.yaml:14` min 3, `:22` target 70%) computes
CPU usage / `requests.cpu` (`api.yaml:47`, 100m). While a request waits for Ollama, the api
pod's thread is blocked on a socket: from the pod's point of view generation is I/O-bound, so CPU
stays near idle however many users are waiting. The HPA therefore measures **JSON parsing,
validation and HTTP handling**, not load. With every request waiting 10 s for the model, CPU can
sit at 10% while latency doubles, and the HPA never scales.

The signal that should scale generation is **demand on the model**: requests in flight per pod,
or queue depth in front of the model, or time-to-first-token / p95 latency. What we would need
to build: export an in-flight gauge from the api (a `prometheus_client.Gauge` incremented around
`generate()` in `services/answer.py`), run Prometheus plus the Prometheus Adapter (or KEDA with
its Prometheus scaler), and point an `autoscaling/v2` HPA at that `Pods` metric. Also note that
more api pods do not help when the bottleneck is one Ollama on one laptop: scaling has to reach
the model servers (`ollama-incluster` replicas, or a hosted provider's rate limit).

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong
The Job's limit is `memory: 1536Mi` with a request of `512Mi` (`k8s/base/indexer-job.yaml:75` and `:72`;
the reindex CronJob template repeats them at `k8s/base/reindex-cronjob.yaml:77` and `:74`). **Peak: 644Mi** of memory (and 991m of CPU), the maximum in
`docs/evidence/kubectl-top-indexer.txt`, sampled with `kubectl top pods -n rahbar -l app=indexer`
over one full reindex run on 8 Nov 2026 (17:34:44 to 17:36:47). metrics-server samples about every
15 s, so a shorter spike between two samples could be missed. The peak is 42% of the 1536Mi limit,
a margin of 892Mi. We left the limits unchanged: the 1.5 x rule of thumb would give about 966Mi,
and the current limit is about 2.4 x the observed peak. If the limit is set below the peak, the kernel kills the container:
`OOMKilled`, **exit code 137**, and because `restartPolicy: OnFailure` with `backoffLimit: 3`,
the pod restarts into the same OOM up to three times (CrashLoopBackOff) before the Job is marked
failed. `kubectl describe pod` shows `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`.
Embedding is where it bites: a 60-page PDF's text, its OCR images at 300 dpi and a batch of
vectors are all in memory at once, far more than answering one query.

## 5. recall@5 by question type: where is it worst, and why?
**Real numbers** from `eval/results.json`, field `recall@5_by_type` (real corpus on minikube,
corrected golden set): exact 0.3333, ordinary 0.7778, version 0.6667, injection 1.0; overall
0.6875. On the fixture set every type scores 1.00 (too small to separate them). On the real
corpus, **exact-term questions** ("What does clause 1.21 require?", "How many grade
points is a B+?") were the worst: 0.33 against 0.78 for ordinary questions, a gap of 0.44, as we expected. A dense embedding represents meaning, and "1.21", "5.4" and
"3.33" carry almost no meaning of their own: "clause 1.21" sits about as close to clause 1.22
(the attendance consequence) as to 1.21 itself, and the prospectus numbers the same rule
"clause 1". The technique from the RAG lecture that addresses it is **hybrid retrieval**: combine
the vector score with a lexical score (BM25 or keyword matching) so exact tokens count. We
implemented a small version, an exact-term boost in re-ranking (`api/app/retrieval/chroma.py`,
`EXACT_BOOST`, line 34), and the next step would be a real BM25 index over the same chunks with
reciprocal rank fusion. The measured gap is in the numbers above. In `eval/retrieved-dump.md` the exact-term misses are
e01 (clause 1.21 itself is not among the top 5) and e02 (the B+ question: the top results are the
HTML grading page, the prospectus and clause 2.6, not the handbook's Grade Points section); only
e03 (clause 5.4) is found.

## 6. EMBED_MODEL changed on the API only: what does your system do?
The api compares its `EMBED_MODEL` with the `embed_model` the indexer wrote into the collection
metadata (`indexer/pipeline/store.py:54-55`), in `ChromaRetriever.check_pin`
(`api/app/retrieval/chroma.py:88`), called at startup (`api/app/main.py:43`) and on every
`/readyz` (`api/app/routes/health.py:42`). On a mismatch, `/readyz` returns 503 naming both
models, so after the restart every api pod sits at **0/1 READY**, is never added to the Service,
and logs one ERROR line, `"refusing to become ready"`, with `index_embed_model` and
`api_embed_model`. A direct call to `/api/ask` gets 503 with the same reason. During a rolling
restart `maxUnavailable: 0` (`api.yaml:17`) means the old, correct pods keep serving while the
new ones refuse, so users are not affected and the rollout simply never finishes:
`kubectl rollout status` hangs, which is the alarm. We ran this locally: index `hash-bow-768`,
api `nomic-embed-text`, readyz body
`{"failed":{"embed_model":"embedding model mismatch: index built with 'hash-bow-768', api EMBED_MODEL='nomic-embed-text'"}}`.

**Without the guardrail** the api would embed questions with a different model from the one
that embedded the chunks. The vectors would have the same length if both models are 768-d, so
Chroma raises nothing; cosine similarity between unrelated vector spaces returns essentially
random neighbours with plausible-looking scores, the model answers confidently from the wrong
passages, and no error appears anywhere. If the dimensions differ, Chroma would reject the
query, which shows up as 500s rather than garbage: still an outage.

## 7. The failure that cost us more than an hour
The failure that cost us the most time was the CI `e2e-eval` job timing out. The api pods crashed with `Could not connect to a Chroma server`. We first suspected the CI and Trivy setup and looked there, and that was the wrong place.

What showed the real cause was Chroma's own log, not the api's. The api's message only says it cannot reach Chroma, which is a symptom. Chroma's log said `invalid type: found string "tcp://10.96.28.126:8000", expected u16 for key "PORT"`. So Chroma was crashing while reading its own settings, and nothing was listening for the api to connect to.

The cause is a Kubernetes default called service links. For every Service in the namespace, Kubernetes adds environment variables to every pod. Our Service is named `chroma`, so every pod received `CHROMA_PORT=tcp://10.96.28.126:8000`. Chroma treats every `CHROMA_*` variable as its own configuration, so it tried to use that text as its port. A port has to be a number (`u16`, 0 to 65535), so it failed.

The fix is `enableServiceLinks: false` in the pod spec of every workload: `k8s/base/api.yaml:24`, `k8s/base/chroma-statefulset.yaml:22`, `k8s/base/indexer-job.yaml:21`, `k8s/base/reindex-cronjob.yaml:25`, `k8s/base/ui.yaml:17` and `k8s/base/redis.yaml:32`. It went in with commit `4648989`, which also carried the CVE patches. Nothing depended on the injected variables, because the api finds Chroma by name through `CHROMA_HOST` and `CHROMA_PORT` in the ConfigMap (`k8s/base/configmap.yaml:16-17`).

The lesson: when a dependency will not start, read the dependency's own log first, before reworking the pipeline that reported the symptom. A second lesson is that a Service name can collide with a program's own environment-variable prefix.
