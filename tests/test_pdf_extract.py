"""Extraction from PDF bytes: `prototype/README.md` item 1, from small generated PDFs."""

from pathlib import Path

import pymupdf
import pytest

from offprint.adapters.pdf.extract import crop, document_facts, read_pages
from offprint.profiles import load_profile

STYLES = load_profile("frontiers").fonts


def wrap_content(doc: pymupdf.Document, page: pymupdf.Page, before: bytes, after: bytes) -> None:
    xref = page.get_contents()[0]
    doc.update_stream(xref, before + b"\n" + doc.xref_stream(xref) + b"\n" + after)


@pytest.fixture
def pdf() -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 50), "VISIBLE")
    return doc


def page_text(doc: pymupdf.Document) -> str:
    return "".join(
        span.text
        for page in read_pages(doc, STYLES)
        for block in page.blocks
        for line in block.lines
        for span in line.spans
    )


def test_actual_text_does_not_replace_the_visible_text(pdf: pymupdf.Document) -> None:
    wrap_content(pdf, pdf[0], b"/Span <</ActualText (HIDDEN ALT TEXT)>> BDC", b"EMC")

    assert "VISIBLE" in page_text(pdf)
    assert "HIDDEN" not in page_text(pdf)


def test_figure_alt_comes_from_the_structure_tree(pdf: pymupdf.Document) -> None:
    wrap_content(pdf, pdf[0], b"/Figure <</MCID 0>> BDC", b"EMC")
    xref = pdf.get_new_xref()
    pdf.update_object(xref, f"<</S/Figure/ActualText(a brain)/K 0/Pg {pdf[0].xref} 0 R>>")

    assert read_pages(pdf, STYLES)[0].figure_alts == ("a brain",)


def test_figure_alts_follow_drawing_order(pdf: pymupdf.Document) -> None:
    wrap_content(pdf, pdf[0], b"/Figure <</MCID 1>> BDC EMC /Figure <</MCID 0>> BDC", b"EMC")
    for mcid, alt in ((0, "second"), (1, "first")):
        xref = pdf.get_new_xref()
        pdf.update_object(xref, f"<</S/Figure/ActualText({alt})/K {mcid}/Pg {pdf[0].xref} 0 R>>")

    assert read_pages(pdf, STYLES)[0].figure_alts == ("first", "second")


def test_a_page_without_alt_text_has_none(pdf: pymupdf.Document) -> None:
    assert read_pages(pdf, STYLES)[0].figure_alts == ()


def test_styles_come_from_the_profile(pdf: pymupdf.Document) -> None:
    pdf[0].insert_text((20, 80), "styled", fontname="tibo")

    spans = [
        span
        for block in read_pages(pdf, STYLES)[0].blocks
        for line in block.lines
        for span in line.spans
    ]

    assert {span.text: span.bold for span in spans} == {"VISIBLE": False, "styled": True}


def test_pages_are_one_based_and_sized(pdf: pymupdf.Document) -> None:
    page = read_pages(pdf, STYLES)[0]

    assert (page.number, page.width, page.height) == (1, 200, 200)
    assert page.blocks[0].page == 1


def test_facts_strip_font_subset_prefixes(fixtures) -> None:
    path: Path = fixtures("frontiers-frai-2026-1748985") / "paper.pdf"

    with pymupdf.open(path) as doc:
        facts = document_facts(doc)

    assert "MinionPro-Regular" in facts.fonts
    assert "frontiersin.org" in facts.text


def test_crops_are_coloured_or_grayscale_on_request(pdf: pymupdf.Document) -> None:
    box = (0.0, 0.0, 100.0, 50.0)

    colour = crop(pdf, page=1, bbox=box, zoom=2, grayscale=False, asset_id="c")
    gray = crop(pdf, page=1, bbox=box, zoom=2, grayscale=True, asset_id="g")

    assert (colour.width, colour.height, colour.mime) == (200, 100, "image/png")
    assert pymupdf.Pixmap(colour.bytes).n == 3
    assert pymupdf.Pixmap(gray.bytes).n == 1
