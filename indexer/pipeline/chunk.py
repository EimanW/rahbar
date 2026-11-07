"""Stage 3: Chunk. Structure-aware, with overlap.

Unit: a "token" here is a whitespace-separated word. Real model tokens are ~1.3x that;
PIPELINE.md states the unit so the numbers are not misread.

Order of splitting, as the RAG lecture lays it out:
  1. sections: a new section starts at a heading line (Markdown '#', a numbered clause
     like '5.4 Academic Warning' or '1.21', or a short ALL-CAPS line);
  2. paragraphs inside a section, packed together while they fit under `size`;
  3. sentences, only for a paragraph that alone is larger than `size`.
Overlap: the last `overlap` words of a chunk are repeated at the start of the next chunk
in the SAME section, so a definition cut at a boundary is still whole in one of them.
Overlap never crosses a section boundary: a chunk never mixes two clauses.

Each chunk's text starts with "[source | section]" so the embedding knows where it sits.
"""

from __future__ import annotations

import re

from .models import Chunk, Document

_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
# "5.4 Academic Warning", "1.21 Attendance", "3. Repeating a course", "Section 4"
_NUMBERED = re.compile(r"^\s*((?:section|clause|chapter|article)\s+)?(\d{1,2}(?:\.\d{1,3}){0,3})\.?\s+"
                       r"([A-Z][^.:;!?]{1,80})$", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")


def heading_of(line: str) -> str | None:
    """Return the section name if this line is a heading, else None."""
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return None
    m = _MD_HEADING.match(stripped)
    if m:
        return m.group(1).strip()
    m = _NUMBERED.match(stripped)
    if m and not stripped.endswith((".", ",", ";")) and len(stripped.split()) <= 12:
        return stripped
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and len(stripped.split()) <= 8:
        return stripped.title()
    if _is_title_case_heading(stripped):
        return stripped
    return None


_MINOR = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the",
          "to", "under", "with", "via", "&", "/"}


def _is_title_case_heading(line: str) -> bool:
    """Unnumbered sub-headings such as 'Attendance Requirements' or 'Repeating a Course'.
    Strict on purpose, because wrapped PDF lines are also short: 2 to 8 words, no trailing
    punctuation or page number (table-of-contents lines end in one), every significant
    word capitalised, and it starts with a capital letter."""
    words = line.split()
    if not 2 <= len(words) <= 8 or len(line) > 70 or not line[0].isupper():
        return False
    if line[-1] in ".,;:" or line[-1].isdigit() or any(ch in line for ch in "()=%"):
        return False
    significant = [w for w in words if w.lower() not in _MINOR]
    return bool(significant) and all(w[0].isupper() for w in significant if w[0].isalpha())


def _sections(doc: Document) -> list[tuple[str, int, list[str]]]:
    """(section name, first page, paragraphs) in document order."""
    out: list[tuple[str, int, list[str]]] = []
    name, page_no = "Introduction", 1
    paras: list[str] = []
    buf: list[str] = []

    def flush_para() -> None:
        if buf:
            paras.append(" ".join(" ".join(buf).split()))
            buf.clear()

    for page in doc.pages:
        for line in page.text.splitlines():
            head = heading_of(line)
            if head is not None:
                flush_para()
                if paras:
                    out.append((name, page_no, paras))
                name, page_no, paras = head, page.page, []
            elif not line.strip():
                flush_para()
            elif line.lstrip().startswith("|"):
                flush_para()                 # keep each table row its own paragraph
                paras.append(line.strip())
            else:
                buf.append(line.strip())
        flush_para()
    if paras:
        out.append((name, page_no, paras))
    return out


def _split_long(paragraph: str, size: int) -> list[str]:
    """A paragraph that fits is one unit. A longer one becomes its sentences; a single
    sentence longer than `size` is hard-split as a last resort."""
    if len(paragraph.split()) <= size:
        return [paragraph]
    units: list[str] = []
    for sentence in _SENTENCE.split(paragraph):
        sw = sentence.split()
        for i in range(0, len(sw), size):
            units.append(" ".join(sw[i:i + size]))
    return units


def chunk(doc: Document, size: int, overlap: int) -> list[Chunk]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError(f"need size > 0 and 0 <= overlap < size, got {size}, {overlap}")
    chunks: list[Chunk] = []
    for section, page, paragraphs in _sections(doc):
        units = [u for para in paragraphs for u in _split_long(para, size)]
        current: list[str] = []
        carried = 0                          # words at the start of `current` that are overlap
        for unit in units:
            uw = unit.split()
            if current and len(current) + len(uw) > size and len(current) > carried:
                chunks.append(_make(doc, section, page, current, len(chunks)))
                keep = min(overlap, size - len(uw))     # overlap never pushes past size
                current = current[-keep:] if keep > 0 else []
                carried = len(current)
            current.extend(uw)
        if len(current) > carried or (current and not chunks):
            chunks.append(_make(doc, section, page, current, len(chunks)))
    return chunks


def _make(doc: Document, section: str, page: int, words: list[str], n: int) -> Chunk:
    slug = re.sub(r"[^a-z0-9]+", "-", doc.source.lower()).strip("-")[:60]
    body = " ".join(words)
    return Chunk(
        id=f"{slug}-{n:04d}",
        text=f"[{doc.source} | {section}]\n{body}",
        source=doc.source,
        section=section,
        page=page,
        doc_version=doc.doc_version,
        superseded=doc.superseded,
    )


def fixed_size_chunk(doc: Document, size: int) -> list[Chunk]:
    """The deliberately bad chunker for FAILURE-ANALYSIS stage B: fixed windows, no
    overlap, no structure. Selected with CHUNKER=fixed. Never the default."""
    words = " ".join(p.text for p in doc.pages).split()
    return [_make(doc, "unknown", 1, words[i:i + size], i // size)
            for i in range(0, len(words), size)]
