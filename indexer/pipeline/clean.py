"""Stage 2: Clean. Remove artefacts without destroying structure.

Rules (also in docs/PIPELINE.md):
1. A line that repeats on at least half of a document's pages (and on 3+ pages) is a
   running header or footer: drop it.
2. A line that is only a page number ("12", "Page 12", "12 of 53", "- 12 -") is dropped.
3. A word hyphenated across a line break is joined ("regis-\\ntration" -> "registration").
4. Runs of spaces collapse to one; runs of blank lines collapse to one blank line.

Deliberately NOT stripped: headings and numbered clause labels ("5.4", "1.21 Attendance").
Chunking takes its section names from them and citations point at them.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace

from .models import Document, Page

_PAGE_NUMBER = re.compile(r"^\s*(-\s*)?(page\s+)?\d{1,4}(\s*(of|/)\s*\d{1,4})?(\s*-)?\s*$", re.I)
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


def _norm(line: str, page: int | None = None) -> str:
    # a running footer differs between pages only by the page's own number
    # ("Page 3 of 53"), so that number, as a standalone token, becomes '#'. Clause numbers
    # such as "5.3" are not standalone tokens and are never touched.
    text = " ".join(line.split()).lower()
    if page is not None:
        text = re.sub(rf"(?<![\d.]){page}(?![\d.])", "#", text)
    # front-matter footers end in a roman page number ("... Regulations 2026 III")
    return re.sub(r"\s*\b[ivxlc]{1,6}$", "", text)


def repeating_lines(pages: list[Page]) -> set[str]:
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({_norm(ln, page.page) for ln in page.text.splitlines() if ln.strip()})
    threshold = max(3, len(pages) // 2)
    return {line for line, n in counts.items() if n >= threshold and len(line) < 120}


def clean_text(text: str, drop: set[str], page: int | None = None) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    kept = []
    for line in text.splitlines():
        if line.strip() and (_norm(line, page) in drop or _PAGE_NUMBER.match(line)):
            continue
        kept.append(re.sub(r"[ \t]+", " ", line).rstrip())
    out = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def clean(doc: Document) -> Document:
    drop = repeating_lines(doc.pages)
    pages = [replace(p, text=clean_text(p.text, drop, p.page)) for p in doc.pages]
    return replace(doc, pages=[p for p in pages if p.text])
