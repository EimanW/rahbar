# ADR 0002: Structure-aware chunking, and the metadata every chunk carries

## Status
Accepted · 2026-11-05

## Context
The corpus is policy documents: numbered clauses ("1.21", "5.4"), unnumbered sub-headings
("Attendance Requirements", "Repeating a Course"), long definitions (the 12-part Generative
AI policy), tables (grade points, fees, annual-report statistics) and two editions of the same
handbook. A fixed-size chunker cuts a clause or a definition in half and mixes two clauses in
one chunk, so the retrieved text answers half a question and the citation points at the
wrong section (failure mode B). Two editions of one policy mean the retriever will find the
repealed clause as easily as the current one unless every chunk says which edition it is from
(failure mode E).

## Decision
- **Chunking** (`indexer/pipeline/chunk.py`): split on sections first (Markdown headings,
  numbered clauses, ALL-CAPS lines, strict Title-Case sub-headings), then pack paragraphs up to
  `CHUNK_SIZE` words, then sentences only for a paragraph that alone is too long. `CHUNK_OVERLAP`
  words are repeated between neighbours **within** a section, never across one, so a chunk never
  mixes two clauses. Table rows are kept whole as `| a | b |` lines.
- Each chunk's text begins with `[source | section]`, so the embedding knows where it sits and
  the model sees the label it must cite.
- **Unit:** words, not model tokens (nomic and llama tokens are about 1.3 words). Stated in
  docs/PIPELINE.md so numbers are not misread.
- **Metadata on every chunk:** `source`, `section`, `page`, `doc_version`, `superseded`.
  `doc_version` and `superseded` come from `corpus/sources.yaml` via `_index.json`.
- **Ids are stable**: `<file-slug>-<n>`, so the same document and position give the same id.
- **Contract change:** `RetrievedRef` (and `Passage`) gained `superseded: bool = False`, so the
  eval can measure stale citations (docs/PIPELINE.md, "A fourth gate"). It has a default, so the
  UI and older callers are unaffected.

## Options considered
- Fixed-size windows: simplest, and the FAILURE-ANALYSIS stage B experiment shows recall@5
  falling from 1.00 to 0.00 on the fixture set, because no chunk carries a section.
- Recursive character splitting (LangChain-style) with no heading awareness: keeps paragraphs
  but loses the section label that citations and recall@k are matched on.
- One chunk per numbered clause: precise, but many clauses are one line, which makes tiny chunks
  with too little context, and the unnumbered sub-headings would be lost.

## Consequences
- Easier: citations are specific ("Freezing of Semester", not "4. Registration"); the
  superseded filter is a metadata `where` clause, not a prompt instruction.
- Harder: heading detection is heuristic. A wrapped PDF line in Title Case can become a false
  heading; the detector is strict (2 to 8 words, no trailing punctuation or page number) to
  limit that, and PIPELINE.md records what was checked.
- Watch: storage amplification (stored words / original words) grows with overlap; the
  indexer logs it on every run.
