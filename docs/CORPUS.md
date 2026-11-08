# Corpus

Source: the FAST-NUCES public website (nu.edu.pk), public pages only (no SLATE, Flex, NU Mail
or anything behind a login). The PDFs are **not committed**: `corpus/sources.yaml` lists them,
`corpus/fetch.py` downloads them one at a time with a pause, and `corpus/MANIFEST.md` records
each URL with its size and SHA-256 (`python corpus/fetch.py --verify` re-checks the bytes).

Documents: 9 listed in `sources.yaml` (7 PDFs, 2 HTML pages), plus 1 left out on purpose · Pages: the two
handbooks alone are about 58 and 64 pages and the annual reports 33 and 85 pages, totaling 279 PDF pages,
so the 40-page minimum is passed several times over. Exact page counts per file: 279 pages total (from `pypdf`/`pdfinfo corpus/raw/*.pdf`).

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | All of `corpus/sources.yaml`: two editions of the academic rules, the prospectus rules, the Student Handbook, two annual reports, two HTML pages, the ORIC start-up policy | 9 documents, 279 PDF pages total |
| 2 | Two versions of one policy | **Academic Rules Handbook Jun 2026** (`doc_version: 2026-06`, `superseded: false`) supersedes the **Aug 2023** undergraduate rules (`doc_version: 2023-08`, `superseded: true`). The Jun 2025 edition 404'd on 8 Nov 2026 | The handbook states that its contents supersede all rules notified earlier. Recorded per chunk as `doc_version` + `superseded`; the retriever filters `superseded: false` unless the question asks for an older edition (`api/app/retrieval/chroma.py`, `wants_older_version`). The Prospectus 2026 rules are the same rules with **different clause numbers** (attendance is clause 1 there, 1.21 in the handbook), a second version trap |
| 3 | Scanned, image-only PDF | Faculty Entrepreneurship and Technical Start-ups Policy (ORIC policy 27) | No text came back when the instructor checked it. Proof: `pdffonts corpus/raw/faculty-entrepreneurship-and-technical-start-ups-policy.pdf` prints an empty font list (0 fonts found). The extract stage OCRs pages with fewer than 40 characters of text and logs `ocr_pages` (pages 1-8 all required OCR) |
| 4 | A table with real information | Grade points table (handbook clause 2.3: A+ 4.00 ... F 0.00); the Fee Structure and Grading HTML pages; the Annual Reports (faculty by campus, graduates, publications) | PDF tables are re-emitted as `| a | b |` rows by `extract.py` so columns stay together; HTML tables likewise. Before/after example in PIPELINE.md |
| 5 | Long definitions | Student Handbook Jun 2026, section XII "Policy on Generative AI Based Tools": 12 numbered sub-sections (Introduction, Objectives, Guidelines for Use, Acceptable Uses, Unacceptable Uses, ... Review and Revision) | A fixed-size chunker cuts "Acceptable Uses" and "Unacceptable Uses" mid-list, so a question about what is allowed retrieves half of what is prohibited. Golden question q08 targets it |
| 6 | A deliberately absent topic | **Hostel rules.** We leave out the prospectus's "Transport and Hostel Facilities" PDF. The Student Handbook only says an in-campus hostel exists at the Chiniot-Faisalabad and Peshawar campuses, with no rules | Students plausibly ask about curfews, room allotment and hostel fees, and the handbook's one sentence about hostels makes a confident wrong answer tempting. Golden a01, a02 must abstain |
| 7 | Exact-term content | Clause numbers (1.21 attendance 100%, 5.4 warning below CGPA 2.00, 4.18 freeze up to 2 semesters, 4.4(c) five courses under warning), grade points (B+ 3.33), fee per credit hour | Embeddings blur numbers, so the retriever adds a small exact-term boost for clause numbers, codes and amounts found in the question (`EXACT_BOOST`). Golden e01 to e03 |

## Why this corpus makes every failure mode reachable
- **A (extraction):** the scanned ORIC policy and the tables.
- **B (chunking):** the 12-part AI policy and multi-clause sections.
- **C (retrieval):** exact clause numbers that a semantic embedding cannot tell apart.
- **E (outdated source):** three editions of the same rules, all still on the website.
- **Abstention:** hostel rules, absent on purpose.

## Known traps on the website (not in our corpus, noted for the viva)
The Academic Calendar shows the 2026-27 schedule next to a holidays table labelled 2023-24;
the Downloads page lists "Prospectus 2025" while the prospectus page says 2026. These are the
same outdated-source problem as property 2.

## Verify before relying on it
The Jun 2025 handbook returned HTTP 404 on 8 Nov 2026 as the university site updated to the 2026 handbook. The Aug 2023 rules PDF (`undergraduate-academic-rules-aug-2023.pdf`, 14,888,226 bytes) downloaded cleanly from `/Student/RulesUndergrad` and serves as the verified superseded edition for property 2.
