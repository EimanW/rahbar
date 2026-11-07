"""Cite only what you retrieved (section 3.4).

A citation is valid when its (source, section) equals a passage retrieved for THIS
request. Invalid citations are removed before the response leaves the API, so a
fabricated citation can never reach the user or the eval. If the model claimed an answer
from context but none of its citations survive, the answer is unsupported and the
pipeline turns it into an honest abstention instead.
"""

from __future__ import annotations

from ..schemas import Citation, Passage


def _key(source: str, section: str) -> tuple[str, str]:
    return source.strip().lower(), " ".join(section.split()).lower()


def filter_citations(citations: list[Citation], passages: list[Passage]) -> tuple[list[Citation], int]:
    """Return (valid citations with the retrieved page filled in, number removed)."""
    by_key = {_key(p.source, p.section): p for p in passages}
    valid, seen = [], set()
    for c in citations:
        k = _key(c.source, c.section)
        if k in by_key and k not in seen:
            p = by_key[k]
            valid.append(Citation(source=p.source, section=p.section, page=p.page))
            seen.add(k)
    return valid, len(citations) - len(valid)
