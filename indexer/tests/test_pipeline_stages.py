"""The five stages, without a Chroma server or a model."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pipeline import store as store_mod
from pipeline.chunk import chunk, fixed_size_chunk, heading_of
from pipeline.clean import clean, clean_text, repeating_lines
from pipeline.config import IndexerSettings
from pipeline.embed import embed
from pipeline.extract import extract, html_to_text, table_to_rows
from pipeline.models import Document, Page
from pipeline.run import discover, run_pipeline
from tests.test_starter_dummy import FakeClient, FakeCollection

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"


def settings(**kw: object) -> IndexerSettings:
    base = dict(embed_model="hash-bow-256", chroma_host="x", chroma_port=1, collection="rahbar",
                corpus_dir=str(FIXTURES), chunk_size=120, chunk_overlap=20, ollama_url="http://x")
    base.update(kw)
    return IndexerSettings(**base)  # type: ignore[arg-type]


# --- extract -----------------------------------------------------------------------------
def test_markdown_front_matter_is_stripped_and_text_kept() -> None:
    doc = extract(str(FIXTURES / "academic-rules-2026.md"), "2026", False)
    assert doc.pages[0].text.lstrip().startswith("# Margalla")
    assert "doc_version" not in doc.pages[0].text


def test_html_keeps_headings_and_table_rows() -> None:
    html = ("<html><nav>menu</nav><h2>Fee Structure</h2><table><tr><th>Programme</th>"
            "<th>Fee</th></tr><tr><td>BS</td><td>10,000</td></tr></table></html>")
    text = html_to_text(html)
    assert "## Fee Structure" in text and "| BS | 10,000 |" in text and "menu" not in text


def test_table_rows_keep_columns_together() -> None:
    assert table_to_rows([["Grade", "Points"], ["A", "4.00"], [None, None]]) == \
        "| Grade | Points |\n| A | 4.00 |"


@pytest.mark.skipif(not shutil.which("tesseract") or not shutil.which("pdftoppm"),
                    reason="needs tesseract-ocr and poppler-utils (installed in the Dockerfile and CI)")
def test_image_only_pdf_is_detected_and_ocrd(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1700, 600), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    draw.text((80, 200), "Startup policy clause 4.2 equity", fill="black", font=font)
    pdf = tmp_path / "scan.pdf"
    img.save(pdf, "PDF", resolution=200)          # an image, no text layer at all
    doc = extract(str(pdf), "2022", False)
    assert doc.pages[0].ocr is True
    assert "policy" in doc.pages[0].text.lower()


# --- clean -------------------------------------------------------------------------------
def test_running_headers_and_page_numbers_are_removed_but_headings_kept() -> None:
    pages = [Page("h.pdf", i, f"FAST-NUCES Academic Rules Handbook\n5.{i} Clause title\n"
                  f"Body text {i}.\nPage {i} of 4") for i in range(1, 5)]
    drop = repeating_lines(pages)
    out = [clean_text(p.text, drop) for p in pages]
    assert all("Handbook" not in o and "Page" not in o for o in out)
    assert out[0].startswith("5.1 Clause title")
    assert clean_text("regis-\ntration", set()) == "registration"


def test_clean_keeps_document_metadata() -> None:
    doc = clean(Document("a.md", "2023", True, [Page("a.md", 1, "x  y\n\n\n\nz")]))
    assert doc.superseded is True and doc.pages[0].text == "x y\n\nz"


# --- chunk -------------------------------------------------------------------------------
def test_heading_detection() -> None:
    assert heading_of("## 2. Academic warning") == "2. Academic warning"
    assert heading_of("5.4 Academic Warning") == "5.4 Academic Warning"
    assert heading_of("GENERAL RULES") == "General Rules"
    assert heading_of("1.1 A student must attend at least 80 percent of the lectures.") is None
    assert heading_of("Attendance Requirements") == "Attendance Requirements"
    assert heading_of("Repeating a Course") == "Repeating a Course"
    assert heading_of("Freezing of Semester 16") is None            # a table-of-contents line
    assert heading_of("students who fail the course must") is None


def test_chunks_follow_sections_and_carry_metadata() -> None:
    doc = clean(extract(str(FIXTURES / "academic-rules-2026.md"), "2026", False))
    chunks = chunk(doc, size=120, overlap=20)
    sections = [c.section for c in chunks]
    assert "1. Attendance" in sections and "2. Academic warning" in sections
    attendance = next(c for c in chunks if c.section == "1. Attendance")
    assert "80 percent" in attendance.text and "CGPA" not in attendance.text
    assert all(c.doc_version == "2026" and c.superseded is False for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)
    again = chunk(doc, size=120, overlap=20)
    assert [c.id for c in again] == [c.id for c in chunks]       # stable ids


def test_long_sections_split_with_overlap() -> None:
    sentences = " ".join(f"Sentence number {i} defines term {i} at length." for i in range(60))
    doc = Document("d.md", "1", False, [Page("d.md", 1, f"## 1. Definitions\n{sentences}")])
    chunks = chunk(doc, size=60, overlap=10)
    assert len(chunks) > 3
    for a, b in zip(chunks, chunks[1:]):
        tail = a.text.split()[-10:]
        assert b.text.split("\n", 1)[1].split()[:10] == tail
        assert len(a.text.split("\n", 1)[1].split()) <= 60
    assert {c.section for c in chunks} == {"1. Definitions"}


def test_bad_chunk_settings_are_rejected() -> None:
    doc = Document("d.md", "1", False, [Page("d.md", 1, "text")])
    with pytest.raises(ValueError):
        chunk(doc, size=50, overlap=50)


def test_fixed_size_chunker_ignores_structure() -> None:
    doc = clean(extract(str(FIXTURES / "academic-rules-2026.md"), "2026", False))
    assert {c.section for c in fixed_size_chunk(doc, 100)} == {"unknown"}


# --- embed + store -----------------------------------------------------------------------
def test_hash_embedder_is_deterministic_and_unit_length() -> None:
    a, b = embed(["fee per credit hour"], settings())[0], embed(["fee per credit hour"], settings())[0]
    assert a == b and len(a) == 256 and abs(sum(v * v for v in a) - 1) < 1e-9


class SwapCollection(FakeCollection):
    def __init__(self, client: "SwapClient", name: str, metadata: dict) -> None:
        super().__init__(name, metadata)
        self.client = client

    def modify(self, name: str) -> None:
        self.client.collections[name] = self.client.collections.pop(self.name)
        self.name = name


class SwapClient(FakeClient):
    def create_collection(self, name: str, metadata: dict) -> FakeCollection:
        self.collections[name] = SwapCollection(self, name, metadata)
        return self.collections[name]


def test_store_builds_staging_then_swaps_and_records_the_pin() -> None:
    from pipeline.models import Chunk

    client = SwapClient()
    client.create_collection("rahbar", {"embed_model": "old"})       # the live index
    chunks = [Chunk(f"c{i}", f"text {i}", "a.md", "1", 1, "2026", False) for i in range(3)]
    count = store_mod.store(chunks, embed([c.text for c in chunks], settings()), settings(),
                            client=client)
    assert count == 3 and set(client.collections) == {"rahbar"}
    meta = client.collections["rahbar"].metadata
    assert meta["embed_model"] == "hash-bow-256" and meta["dimension"] == 256
    assert meta["hnsw:space"] == "cosine" and meta["index_version"]


def test_store_refuses_an_empty_index() -> None:
    with pytest.raises(ValueError, match="empty"):
        store_mod.store([], [], settings(), client=SwapClient())


def test_full_pipeline_on_the_fixture_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SwapClient()
    monkeypatch.setattr(store_mod, "get_client", lambda s: client)
    count = run_pipeline(settings())
    rows = client.collections["rahbar"].rows
    assert count == len(rows) > 5
    sources = {meta["source"] for _d, _e, meta in rows.values()}
    assert sources == {p.name for p, _v, _s in discover(str(FIXTURES))}
    old = [m for _d, _e, m in rows.values() if m["source"] == "academic-rules-2023.md"]
    assert old and all(m["superseded"] is True for m in old)


def test_pdf_table_becomes_rows_and_the_text_above_it_survives() -> None:
    """tests/data/grade-table.pdf: a paragraph, then a 4-column grade table (made with
    reportlab). The paragraph's last line sits right above the table."""
    doc = extract(str(Path(__file__).parent / "data" / "grade-table.pdf"), "x", False)
    text = doc.pages[0].text
    assert "every semester." in text
    assert "| B+ | 3.33 | D+ | 1.33 |" in text
