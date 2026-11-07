"""Stage 1: Extract. PDF, HTML, Markdown or text to text, page by page.

PDF pages with no text layer (fewer than MIN_TEXT_CHARS characters) are rendered to an
image and OCR'd with Tesseract; those pages are marked ocr=True and logged, so
docs/PIPELINE.md can say which documents needed OCR. Tables found by pdfplumber are
re-emitted as pipe-separated rows so their columns stay together instead of being
interleaved with the surrounding text (failure mode A).
"""

from __future__ import annotations

import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

from .models import Document, Page

MIN_TEXT_CHARS = 40
# Set to False only to reproduce failure stage A (OCR=false in the ConfigMap).
OCR_ENABLED = True


def _log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer.extract", "msg": msg, **fields}),
          file=sys.stdout, flush=True)


def extract(path: str, doc_version: str, superseded: bool) -> Document:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        pages = _extract_pdf(p)
    elif suffix in {".html", ".htm"}:
        pages = [Page(source=p.name, page=1, text=html_to_text(p.read_text("utf-8", "replace")))]
    elif suffix in {".md", ".txt"}:
        pages = [Page(source=p.name, page=1, text=strip_front_matter(p.read_text("utf-8")))]
    else:
        raise ValueError(f"unsupported document type: {p.name}")
    ocr_pages = [pg.page for pg in pages if pg.ocr]
    _log("extracted", source=p.name, pages=len(pages), ocr_pages=ocr_pages,
         chars=sum(len(pg.text) for pg in pages))
    return Document(source=p.name, doc_version=doc_version, superseded=superseded, pages=pages)


def strip_front_matter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1:]).strip() + "\n"
    return text


def table_to_rows(table: list[list[str | None]]) -> str:
    """Render a pdfplumber table as one '| a | b |' line per row."""
    rows = []
    for row in table:
        cells = [" ".join((c or "").split()) for c in row]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _extract_pdf(path: Path) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(str(path)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if tables:
                # keep every character that is not inside a table, then append each table
                # as rows. (Cropping with outside_bbox() also cut the text line just above a
                # table whose box touched it; filtering per character does not.)
                boxes = [t.bbox for t in tables]
                outside = page.filter(lambda obj: not _inside_any(obj, boxes))
                text = outside.extract_text() or ""
                rendered = [table_to_rows(t.extract()) for t in tables]
                text = text + "\n\n" + "\n\n".join(r for r in rendered if r)
            else:
                text = page.extract_text() or ""
            if len(text.strip()) < MIN_TEXT_CHARS and not OCR_ENABLED:
                pages.append(Page(source=path.name, page=number, text=text))
            elif len(text.strip()) < MIN_TEXT_CHARS:
                pages.append(Page(source=path.name, page=number, text=_ocr_page(path, number),
                                  ocr=True))
            else:
                pages.append(Page(source=path.name, page=number, text=text))
    return pages


def _inside_any(obj: dict, boxes: list[tuple[float, float, float, float]]) -> bool:
    if "x0" not in obj or "top" not in obj:
        return False
    for x0, top, x1, bottom in boxes:
        if (obj["x0"] >= x0 - 1 and obj["x1"] <= x1 + 1
                and obj["top"] >= top - 1 and obj["bottom"] <= bottom + 1):
            return True
    return False


def _ocr_page(path: Path, number: int) -> str:
    """Render one page at 300 dpi and OCR it. Needs tesseract-ocr and poppler-utils."""
    import pytesseract
    from pdf2image import convert_from_path

    images = convert_from_path(str(path), dpi=300, first_page=number, last_page=number)
    return "\n".join(pytesseract.image_to_string(img, lang="eng") for img in images)


class _HTMLText(HTMLParser):
    """HTML to text that keeps headings as Markdown headings and tables as rows."""

    _SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
    _BLOCK = {"p", "div", "li", "br", "section", "article", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._heading: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading = int(tag[1])
            self.out.append("\n\n" + "#" * self._heading + " ")
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._heading = None
            self.out.append("\n\n")
        elif tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.out.append("\n| " + " | ".join(self._row) + " |")
            self._row = None
        elif tag == "table":
            self.out.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._row is None:
            self.out.append(data if self._heading is None else " ".join(data.split()))


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
