# Failure analysis

Four of the six stages broken on purpose, one at a time, then restored (section 5.5). Each was
run on a local stack: a real Chroma 1.0.12 server, the real indexer, the api with
`LLM_PROVIDER=stub` and `EMBED_MODEL=hash-bow-768`, scored with `eval/run_eval.py` against the
CI fixture golden set (6 questions) and its committed baseline (recall@5 1.00). Every number
below is from those runs. The switches used are real configuration (`OCR`, `CHUNKER`,
`TOP_K`, `EMBED_MODEL`, `FILTER_SUPERSEDED`), so each break is one ConfigMap edit on the cluster.

From the RAG lecture: only F is the model's fault, so check A to E first. Stages D and F need a
real model and were not run: this local stack uses the stub provider, so there is no model to break.

## Stage A · Extraction
- **What we broke:** `OCR=false`, then indexed an image-only PDF (one page with no text layer;
  `pdffonts` prints an empty font list). This is what indexing the scanned ORIC policy without
  OCR does.
- **Symptom:** the Job log said `"msg": "extracted", "ocr_pages": [], "chars": 0`, then
  `"chunks": 0`. With that file alone the Job failed with
  `ValueError: refusing to replace the index with an empty one`, by design. Inside a full corpus
  the document would simply vanish: every other file indexes, and questions about start-up equity
  would get honest abstentions or, worse, answers from a neighbouring policy.
- **Diagnosis, as if we had not caused it:** the per-document Job log. `chars: 0` or a
  near-zero `chars` for a multi-page PDF is the tell, and the indexer now also logs
  `"WARNING document produced no chunks"` with `ocr_enabled`. On the query side, recall@5 for
  questions whose golden source is that file is 0 while their best `top_scores` are low.
- **Remedy:** `OCR=true` (the default). Same file: `"ocr_pages": [1], "chars": 107`, 1 chunk,
  Job finished. The OCR path is covered by `test_image_only_pdf_is_detected_and_ocrd`.

## Stage B · Chunking
- **What we broke:** `CHUNKER=fixed`, `CHUNK_SIZE=100`, `CHUNK_OVERLAP=0`: fixed 100-word windows
  with no structure, the handout's suggested break.
- **Symptom:** the gate failed: `recall@5 0.000 is more than 5% below the baseline 1.000`.
  Chunks fell from 11 to 6 and amplification rose from 1.005 to 1.042. The answers still came
  back, with valid citations (citation validity stayed 1.00), because the stub cites whatever
  was retrieved: the system looked fine to a user.
- **Diagnosis, as if we had not caused it:** recall@k dropping across every question type at
  once points at indexing, not at one kind of question. The retrieved `section` values in the
  api log line and in `results.json` are all `unknown`, and a fixed window cuts "2. Academic
  warning" from its clause text. A one-line check: `kubectl logs job/<id> | grep "chunked"`
  shows `chunker: fixed`.
- **Remedy:** back to `CHUNKER=structure`, re-index (`make index`): recall@5 1.00, 11 chunks.

## Stage C · Retrieval
Two breaks.

**C1, `TOP_K=1`.**
- **Symptom:** gate failed, `recall@5 0.800 is more than 5% below the baseline 1.000`
  (recall@3 0.80 as well). One answerable question lost its relevant passage because it was the
  second-best match, not the first.
- **Diagnosis:** the per-request log line shows `top_k: 1` and a single `chunk_ids` entry;
  recall@3 equal to recall@5 is impossible with k=5 unless k is smaller.
- **Remedy:** `TOP_K=5`.

**C2, `EMBED_MODEL` changed on the api only** (index built with `hash-bow-768`, api restarted with
`nomic-embed-text`).
- **Symptom:** no garbage answers, because the guardrail caught it. `/readyz` returned 503:
  `"embedding model mismatch: index built with 'hash-bow-768', api EMBED_MODEL='nomic-embed-text'"`,
  so on the cluster the pods sit at 0/1 READY and get no traffic. A direct `POST /api/ask`
  first returned a **500** here, which we fixed during this exercise: it now returns 503 with the
  same reason (`routes/ask.py`, `test_ask_returns_503_not_500_when_the_pin_is_broken`). `/healthz`
  stayed 200, so the kubelet did not restart anything.
- **Diagnosis:** `kubectl get pods` shows `0/1 READY` with no restarts; `kubectl logs` shows the
  `"refusing to become ready"` ERROR line naming both models.
- **Remedy:** put `EMBED_MODEL` back, or re-index with the new model, then
  `kubectl rollout restart deployment/api`. Without the guardrail the vectors would be compared
  across two models: retrieval returns unrelated chunks with plausible scores and nothing errors.

## Stage E · Source
- **What we broke:** `FILTER_SUPERSEDED=false`, so superseded (2023) chunks are retrievable for
  every question.
- **Symptom:** the 2023 chunk ranked **first** for three questions (the api log's `chunk_ids`
  began with `academic-rules-2023-md-...`), so the answer cited the repealed edition. But
  **recall@5 stayed at 1.00** and the original three gates **passed**, because the current
  chunk was still somewhere in the top 5.
- **Diagnosis, as if we had not caused it:** only by looking at which edition was cited. This is
  why we added a stale-citation measure: the api now returns `superseded` on each retrieved
  passage, and the eval counts citations of superseded documents on questions that did not ask
  for an older version. With the filter off: `stale citations: 60.0%`, gate failed. With it on:
  0.0%, gate passed. In production the same signal is `superseded: true` entries in the
  retrieved list of the per-request log line.
- **Remedy:** `FILTER_SUPERSEDED=true` (the default). The filter is metadata, not a prompt: a
  prompt saying "prefer the newest edition" cannot fix a retriever that already put the old one
  first.

## Stage D · Prompt, and Stage F · Generation (not run)
Need a real model. How we would read them if they happened:
- **D (no "use the supplied context" rule):** answers start containing facts that are in no
  retrieved chunk; must-abstain questions get answered. Signals: abstention correctness below 1.00
  and `rahbar_citations_removed_total` rising, because the model cites things it never saw.
- **F (temperature 1.2):** the same question gives different answers run to run, JSON validity
  falls, so `rahbar_generation_retries_total` and `rahbar_fallbacks_total` rise. Retrieval metrics
  stay identical, which is how you know it is F and not A to E.
