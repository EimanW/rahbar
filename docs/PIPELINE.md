# Indexing and retrieval pipeline

Two paths that never share a process (ADR 0001): the **indexer Job** writes the index once,
and again when the documents change; the **api** reads it on every question.

```
indexer Job:  discover -> extract -> clean -> chunk -> embed -> store (staging, then swap)
api:          validate -> cache? -> embed -> retrieve (+filter, +exact boost) -> floor
              -> augment -> generate (schema) -> validate/retry/fallback -> citation check
              -> cache store (if safe) -> one JSON log line
```

Where numbers below say **fixture**, they were measured on the CI fixture corpus
(`eval/fixtures`, 3 short documents) on a local stack: a real Chroma 1.0.12 server, the real
indexer, the api, `EMBED_MODEL=hash-bow-768`, `LLM_PROVIDER=stub`. Rows marked **TODO(team)**
must be measured on the real corpus on minikube with `nomic-embed-text`, using
`scripts/sweep_chunking.sh`; no number below was guessed.

## How documents reach the Job
The indexer image is built from the repository root (`indexer/Dockerfile`) and carries
`eval/fixtures` at `/fixtures` always, and `corpus/raw/` at `/corpus` when it exists on the
machine that builds it (`make fetch` then `make images`). `corpus/raw/` is gitignored, so images
built by CI and pushed to Docker Hub carry only the fixtures: we never republish the
university's PDFs. `CORPUS_DIR` in the ConfigMap picks which folder is indexed (`/corpus` on
minikube, `/fixtures` in the ci overlay). Re-fetching new documents therefore means
`make fetch images` and a re-index, not an api redeploy.

## Extraction
`indexer/pipeline/extract.py`
- PDFs with `pdfplumber`, page by page. A page with fewer than 40 characters of text has no
  text layer: it is rendered at 300 dpi (`pdf2image`, poppler) and OCR'd with Tesseract, and
  marked `ocr=True`. Each document logs `ocr_pages`, so the Job log lists which documents
  needed OCR. `indexer/tests/test_pipeline_stages.py::test_image_only_pdf_is_detected_and_ocrd`
  builds an image-only PDF and checks that the OCR text comes back.
- Tables: `pdfplumber.find_tables()`; the text outside the tables is extracted normally and each
  table is appended as one `| cell | cell |` line per row. HTML pages: headings become
  Markdown headings, `<tr>` rows become `| ... |` lines, nav, header and footer are dropped.
- **Which documents needed OCR:** the ORIC start-up policy is expected to be the only one.
  TODO(team): confirm from the Job log line `"msg": "extracted"`, field `ocr_pages`.

**Before and after, a table.** Measured on `indexer/tests/data/grade-table.pdf` (the clause 2.3
grade-points layout: a paragraph, then a 4-column table; made with reportlab so the test is
reproducible). Plain `pdfplumber extract_text()`:
```
Grade Points Grade Points
A+ 4.00 C+ 2.33
B+ 3.33 D+ 1.33
```
The rows survive, but the column boundaries do not: "A+ 4.00 C+ 2.33" is four tokens with
nothing saying which number belongs to which grade, and a chunk boundary inside the table loses
the header entirely. Our extractor (`extract.py`, table branch):
```
| Grade | Points | Grade | Points |
| A+ | 4.00 | C+ | 2.33 |
| B+ | 3.33 | D+ | 1.33 |
```
Building this example also exposed a real bug in our first version: cropping the page with
`outside_bbox(table)` cut the last line of the paragraph just above the table ("...GPA and CGPA
of a student in" lost "every semester."). We now drop only the characters that lie inside a
table box; `test_pdf_table_becomes_rows_and_the_text_above_it_survives` pins it.
TODO(team): add one real example from the Annual Report tables after your first Job run.

**What we could not recover:** OCR of the scanned policy loses its layout (headers, any table
borders) and may misread clause numbers; we keep the text and accept that its citations are
coarser (section names come only from lines OCR read cleanly).

## Cleaning
`indexer/pipeline/clean.py`
1. A line that repeats on at least half of a document's pages (and 3 or more) is a running
   header or footer, and is dropped. Lines are compared after replacing the page's own number
   (as a standalone token) with `#` and dropping a trailing roman page number, so
   "Undergraduate Academic Rules and Regulations 2026 III" counts as the same line on every page.
2. Lines that are only a page number ("12", "Page 12 of 53", "- 12 -") are dropped.
3. Words hyphenated across a line break are joined.
4. Runs of spaces collapse; runs of blank lines collapse to one.

**Deliberately not stripped:** headings and clause labels ("5.4", "1.21 ...", "Attendance
Requirements"). Chunking takes its section names from them and every citation points at one.
Clause numbers are never touched by the page-number rule, because "5.3" is not a standalone
"3" (`test_running_headers_and_page_numbers_are_removed_but_headings_kept`).

## Chunking
`indexer/pipeline/chunk.py`, decision in ADR 0002. Unit: **words** (model tokens are about
1.3 x words). Sections first (Markdown headings, numbered clauses, ALL-CAPS lines, strict
Title-Case sub-headings), then paragraphs packed under `CHUNK_SIZE`, then sentences for a
paragraph that alone is too long. `CHUNK_OVERLAP` words are repeated between neighbours inside a
section, never across one. Each chunk starts with `[source | section]`.

**Storage amplification** = stored words / original words, logged by every Job run as
`"msg": "chunking summary"`, field `amplification`. The `[source | section]` prefix and the
overlap are what push it above 1. Fixture, 120/20: 429 / 427 = **1.005** (sections there are
shorter than the chunk size, so overlap never triggers). The lecture's example was 150 / 120 =
1.25. Real corpus: TODO(team) from the Job log.

| Size (words) | Overlap (words) | recall@5 | Chunks stored | Corpus |
| --- | --- | --- | --- | --- |
| 40 | 0 | 1.00 | 15 | fixture (amplification 1.052) |
| 60 | 10 | 1.00 | 11 | fixture (amplification 1.005) |
| 120 | 20 | 1.00 | 11 | fixture (amplification 1.005) |
| 100, fixed-size, no structure | 0 | 0.00 | 6 | fixture (failure stage B) |
| 200 | 30 | TODO(team) | TODO(team) | real, `scripts/sweep_chunking.sh` |
| 300 | 50 | TODO(team) | TODO(team) | real (shipped value in the ConfigMap) |
| 500 | 80 | TODO(team) | TODO(team) | real |

**What the fixture rows show, and what they do not.** Every structure-aware setting scores
1.00 on the fixture set because its sections are one or two paragraphs long, shorter than any
chunk size we tried: the fixtures cannot tell 40 words from 120. They do show the one result
that matters for the design: the same text with fixed-size windows and no section labels scores
0.00, because no chunk carries the section the golden answer is under. **Justify the shipped
setting from the real-corpus rows.** The rule we will apply: pick the smallest size within one
point of the best recall@5, because smaller chunks put fewer unrelated sentences in front of a
3B model, and prefer the setting with the better exact-term recall when two tie.

## Embedding
- Model: `nomic-embed-text` (768 dimensions) through Ollama, `POST /api/embed`, batches of
  32 (`indexer/pipeline/embed.py`). nomic is trained with task prefixes, so documents are
  embedded as `search_document: ...` and questions as `search_query: ...`
  (`api/app/embedding.py`).
- **Where the pin lives:** one key, `EMBED_MODEL`, in `k8s/base/configmap.yaml`, read by both
  the indexer and the api (`envFrom: rahbar-config`).
- **How the api checks it:** the indexer writes `embed_model` and `dimension` into the
  collection metadata (`indexer/pipeline/store.py`). The api compares them with its own
  `EMBED_MODEL` at startup and on every `/readyz` (`ChromaRetriever.check_pin`). On a mismatch
  `/readyz` returns 503 naming both models, so the pod stays 0/1 READY, and `/api/ask` returns
  503 instead of retrieving with the wrong vectors. Verified locally: index built with
  `hash-bow-768`, api started with `nomic-embed-text`:
  `{"failed":{"embed_model":"embedding model mismatch: index built with 'hash-bow-768', api EMBED_MODEL='nomic-embed-text'"}}`.
- **CI-only embedder:** `hash-bow-768` (`indexer/pipeline/hashembed.py`, byte-identical copy at
  `api/app/hashembed.py`, enforced by a test). It hashes words and word pairs into 768 buckets:
  a lexical similarity, no network, no download, so the e2e-eval job measures real retrieval in
  CI. It is never used on minikube.

## Retrieval
`api/app/retrieval/chroma.py`
- `top_k` from the ConfigMap (`TOP_K=5`); Chroma is asked for 4 x k candidates.
- **Superseded filter:** `where={"superseded": False}` unless the question explicitly asks about
  an older version ("the 2025 handbook", "previous rules", "superseded"). A bare "earlier" does
  not count: our first version let "ignore earlier instructions" switch the filter off, which we
  caught on the fixture injection question and fixed (`wants_older_version`, tested).
- **Exact-term boost:** clause numbers, course codes and amounts in the question add 0.05 per
  match to a candidate's ranking score (not to the reported similarity). This is a small step
  toward the hybrid (BM25 + vector) retrieval the RAG lecture recommends for exact terms.
- **Relevance floor:** if no passage has similarity >= `RELEVANCE_FLOOR`, the api abstains
  without calling the model. Fixture (hash-bow): the hostel question's best score is 0.00 and the
  weakest answerable one is 0.18, so the ci overlay uses 0.10. Real corpus with nomic: the
  ConfigMap ships 0.50 as a starting point; TODO(team): set it between the highest must-abstain
  score and the lowest answerable score in `eval/results.json` (`per_question[].top_scores`).

## Semantic cache
`api/app/services/cache.py`, ADR 0003. Redis, one hash per `(index_version, embed_model)`.
A hit is cosine >= `CACHE_THRESHOLD` from the ConfigMap. Invalidated on re-index because the
namespace changes with `index_version`. Never cached: follow-ups, abstentions, fallbacks,
answers with a removed citation.

**Thresholds tried** (rule from the lecture: the lowest threshold with zero false hits).
TODO(team), with `nomic-embed-text` on minikube: ask pairs that must hit ("What CGPA avoids
academic warning?" / "minimum CGPA to stay off warning") and pairs that must not ("How many
semesters can I freeze?" / "How many courses can I take on warning?"), at 0.90, 0.93 and 0.95,
and record the false hit that rules a value out:

| Threshold | True hits (of N paraphrase pairs) | False hits (of M different pairs) | Verdict |
| --- | --- | --- | --- |
| 0.90 | TODO(team) | TODO(team) | |
| 0.93 | TODO(team) | TODO(team) | |
| 0.95 | TODO(team) | TODO(team) | shipped until measured |

(With the fixture's lexical embedder the cache hit on exact repeats, verified: the second eval
run served 5 of 6 answers from cache; the abstention was correctly not cached.)

## Evaluation method
`eval/run_eval.py`
- **recall@k** = relevant (source, section) pairs found in the top k retrieved / relevant
  pairs. A retrieved passage matches a golden one when the `source` file is the same and the
  golden `section` is a prefix of the chunk's section, case-insensitive, ignoring a leading
  number on the heading ("Attendance" matches "Attendance Requirements"; "Acceptable Uses"
  matches "4. Acceptable Uses"). Golden sections were written from the documents, not from
  retrieved chunks.
- **Citation validity** = citations that match a retrieved (source, section) / all citations.
  The api already drops invalid citations before responding (`services/citations.py`), so this
  measures that the guard works end to end.
- **Abstention correctness** = must-abstain questions answered with `answered_from_context:
  false` / must-abstain questions. Must be 100%.
- Also reported: recall@5 by question type, false-abstention rate on answerable questions, the
  `expect` string hit rate, and stale citations.

### A fourth gate: stale citations
Breaking stage E on the fixture set (superseded filter off) left **recall@5 at 1.00** while the
2023 chunk ranked first for three questions and **60% of citations named the superseded
document**. The three gates in section 5.4 cannot see that: the current chunk is still in the
top 5. So the api now returns `superseded` for each retrieved passage, and the gate also fails
when any citation names a superseded document for a question that did not ask for an older
version (golden `allow_superseded: true` marks the one that does).

### Shipped numbers
- Fixture (CI baseline, `eval/fixtures/baseline.fixture.json`): recall@3 1.00, recall@5 1.00,
  citation validity 1.00, abstention 1.00, stale citations 0.00 (6 questions).
- Real corpus: `eval/baseline.json` and `eval/results.json`, TODO(team): run
  `python eval/run_eval.py --api http://<ip> --host rahbar.local --update-baseline` on minikube
  after the first index, then commit both files.
