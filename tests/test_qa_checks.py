"""Each check on the smallest document that shows it, so a failure says which rule broke."""

import re
import shutil
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from offprint.extraction import SourceCaption, SourceEquation, SourceEvidence, SourceText
from offprint.ir import (
    Asset,
    Author,
    Document,
    Equation,
    Figure,
    Heading,
    License,
    Meta,
    Provenance,
    Table,
    Text,
)
from offprint.qa import CHECKS, load_config, run_gate
from offprint.qa.book import BookError, read_book, reading_text, xhtml_wellformed
from offprint.qa.checks import (
    counts_equations,
    counts_figures,
    counts_tables,
    figure_foreign_caption,
    meta_required,
    table_empty_header,
    table_ref_rows,
)
from offprint.qa.coverage import readable_texts, word_coverage, word_list
from offprint.qa.epubcheck import parse_report, run_epubcheck
from offprint.render.epub import render_epub

CONFIG = load_config()
PNG = Asset(id="a", mime="image/png", bytes=b"\x89PNG", width=1, height=1)
BOX = (10.0, 10.0, 100.0, 100.0)
META = Meta(title="T", authors=(Author(name="A"),), license=License(spdx="CC-BY-4.0"))


def document(*blocks: object) -> Document:
    provenance = {b.id: Provenance(adapter="test", page=2, bbox=BOX) for b in blocks}
    return Document(meta=META, blocks=blocks, assets={"a": PNG}, provenance=provenance)


def figure(number: str) -> Figure:
    return Figure(id=f"figure-{number}", number=number, asset="a", caption=(Text("c"),))


def table(number: str, *rows: tuple[str, ...], header: tuple[str, ...] = ("H",)) -> Table:
    return Table(
        id=f"table-{number}",
        number=number,
        caption=(Text("c"),),
        header=tuple((Text(cell),) if cell else () for cell in header),
        rows=tuple(tuple((Text(cell),) for cell in row) for row in rows),
    )


def equation(number: str, block_id: str | None = None) -> Equation:
    return Equation(id=block_id or f"equation-{number}", alt="x", number=number, asset="a")


def caption(kind: str, number: str, page: int = 2, *, continued: bool = False) -> SourceCaption:
    return SourceCaption(kind=kind, number=number, page=page, bbox=BOX, continued=continued)


def evidence(*captions: SourceCaption, equations: tuple[str, ...] = ()) -> SourceEvidence:
    numbers = tuple(SourceEquation(number=n, page=2, bbox=BOX) for n in equations)
    return SourceEvidence(pages=2, texts=(), captions=captions, equations=numbers)


def messages(outcome) -> list[str]:
    return [item.message for item in outcome.findings]


# The catalogue


def test_check_ids_are_unique() -> None:
    ids = [check.id for check in CHECKS]

    assert len(ids) == len(set(ids))


def test_every_code_the_other_stages_document_is_a_check() -> None:
    ids = {check.id for check in CHECKS}
    root = Path(__file__).parent.parent
    ir_rows = re.findall(r"^\| (`[a-z_.]+`.*?) \|", (root / "docs/ir.md").read_text(), re.MULTILINE)
    ir_codes = {code for row in ir_rows for code in re.findall(r"`([a-z_]+\.[a-z_]+)`", row)}
    epub = (root / "src/offprint/render/epub/__init__.py").read_text()
    cover = (root / "src/offprint/cover/layout.py").read_text()

    assert "table.width" in ir_codes
    assert ir_codes <= ids
    assert set(re.findall(r"`(epub\.\w+)`", epub)) <= ids
    assert set(re.findall(r'"(cover\.\w+)"', cover)) <= ids


# counts.figures / counts.tables


def test_captions_and_blocks_that_agree_pass() -> None:
    doc = document(figure("1"), figure("2"))

    assert not counts_figures(
        doc, evidence(caption("figure", "1"), caption("figure", "2"))
    ).findings


def test_a_caption_without_a_figure_says_on_which_page() -> None:
    doc = document(figure("1"))

    outcome = counts_figures(doc, evidence(caption("figure", "1"), caption("figure", "2", page=7)))

    assert messages(outcome) == ["the source shows figure 2, but the document doesn't have it"]
    assert outcome.findings[0].page == 7


def test_a_figure_without_a_caption_fires() -> None:
    outcome = counts_figures(document(figure("1")), evidence())

    assert messages(outcome) == ["figure 1 was extracted, but the source doesn't show it"]


def test_a_gap_in_the_numbers_fires_even_without_a_source() -> None:
    outcome = counts_figures(document(figure("1"), figure("3")), None)

    assert messages(outcome) == ["figure 2 is missing from the numbering"]


def test_a_duplicate_number_fires() -> None:
    doc = document(table("1"), replace(table("1"), id="other"))

    assert "table 1 appears 2 times" in messages(counts_tables(doc, None))


def test_a_blank_number_fires() -> None:
    assert messages(counts_tables(document(table("")), None)) == ["a table has no number"]


def test_a_continued_caption_is_not_a_new_table() -> None:
    doc = document(table("1"))
    found = evidence(caption("table", "1"), caption("table", "2", continued=True))

    assert not counts_tables(doc, found).findings


def test_supplementary_numbers_are_a_series_of_their_own() -> None:
    assert not counts_figures(document(figure("1"), figure("S1"), figure("S3")), None).findings


# counts.equations


def test_equations_numbered_once_each_pass() -> None:
    doc = document(equation("1"), equation("2"))

    assert not counts_equations(doc, evidence(equations=("1", "2"))).findings


def test_a_lost_last_equation_is_only_visible_in_the_source() -> None:
    doc = document(equation("1"))

    assert not counts_equations(doc, None).findings
    outcome = counts_equations(doc, evidence(equations=("1", "2")))
    assert messages(outcome) == ["the source shows equation 2, but the document doesn't have it"]
    assert outcome.findings[0].page == 2


def test_a_repeated_equation_number_fires() -> None:
    doc = document(equation("1"), equation("1", "other"))

    assert messages(counts_equations(doc, None)) == ["equation 1 appears 2 times"]


def test_parentheses_around_a_number_do_not_matter() -> None:
    assert not counts_equations(document(equation("(1)")), evidence(equations=("1",))).findings


def test_unnumbered_equations_are_not_counted() -> None:
    doc = document(Equation(id="e", alt="x", asset="a"))

    assert not counts_equations(doc, evidence()).findings


# table.empty_header


def test_named_headers_pass() -> None:
    assert not table_empty_header(document(table("1", header=("A", "B")))).findings


def test_a_phantom_column_fires_with_its_position() -> None:
    outcome = table_empty_header(document(table("3", header=("A", "", "B"))))

    assert messages(outcome) == ["table 3 has an empty header in column 2"]
    assert outcome.findings[0].block_id == "table-3"


# table.ref_rows


def references(*first_cells: str) -> Table:
    return table("3", *((cell, "x") for cell in first_cells), header=("References", "Main"))


@pytest.mark.parametrize("cell", ["Hong et al. (2019)", "Roe (2021a)", "(Raju and Gopi, 2021)"])
def test_reference_rows_that_end_in_a_year_pass(cell: str) -> None:
    assert not table_ref_rows(document(references(cell)), CONFIG).findings


def test_a_reference_row_with_text_after_its_year_fires() -> None:
    doc = document(references("Hong et al. (2019)", "Khan et al. (2022) and performance metrics."))

    outcome = table_ref_rows(doc, CONFIG)

    assert len(outcome.findings) == 1
    assert "table 3 row 2" in outcome.findings[0].message
    assert "performance metrics" in outcome.findings[0].message


def test_other_tables_are_not_held_to_it() -> None:
    assert not table_ref_rows(document(table("1", ("no year",))), CONFIG).findings


# figure.foreign_caption


def test_a_figure_with_only_its_own_caption_passes() -> None:
    doc = document(figure("1"))

    assert not figure_foreign_caption(doc, evidence(caption("figure", "1")), CONFIG).findings


def test_another_caption_inside_the_box_fires() -> None:
    doc = document(figure("1"))
    found = evidence(caption("figure", "1"), caption("table", "2"))

    outcome = figure_foreign_caption(doc, found, CONFIG)

    assert messages(outcome) == ["figure 1 contains the caption of table 2"]


def test_a_caption_on_another_page_or_outside_the_box_is_fine() -> None:
    doc = document(figure("1"))
    outside = replace(caption("figure", "3"), bbox=(200.0, 200.0, 300.0, 300.0))
    found = evidence(caption("figure", "2", page=3), outside)

    assert not figure_foreign_caption(doc, found, CONFIG).findings


def test_a_caption_that_only_touches_the_box_is_fine() -> None:
    doc = document(figure("1"))
    touching = replace(caption("figure", "2"), bbox=(50.0, 90.0, 100.0, 190.0))

    assert not figure_foreign_caption(doc, evidence(touching), CONFIG).findings


def test_the_check_is_skipped_without_a_source() -> None:
    assert figure_foreign_caption(document(figure("1")), None, CONFIG).skipped


# meta.required


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"title": " "}, "the paper has no title"),
        ({"authors": ()}, "the paper has no author"),
        ({"license": None}, "the paper has no license"),
    ],
)
def test_missing_metadata_fires(change: dict, message: str) -> None:
    doc = replace(document(), meta=replace(META, **change))

    assert messages(meta_required(doc)) == [message]


def test_complete_metadata_passes() -> None:
    assert not meta_required(document()).findings


# coverage.words


def source_text(text: str, page: int = 1, bbox: tuple = (0.0, 200.0, 50.0, 210.0)) -> SourceText:
    return SourceText(text=text, page=page, bbox=bbox)


def source(*texts: SourceText, captions: tuple = ()) -> SourceEvidence:
    return SourceEvidence(pages=1, texts=texts, captions=captions, equations=())


def test_ligatures_and_case_do_not_count_as_differences() -> None:
    assert word_list("The Eﬃcient ﬁgure", 5) == ["efficient", "figure"]


def test_words_shorter_than_the_limit_are_not_counted() -> None:
    assert word_list("four letters", 5) == ["letters"]


def test_a_word_in_a_ligature_reaches_the_book() -> None:
    outcome = word_coverage(document(), source(source_text("ﬁgure")), ["figure"], CONFIG)

    assert outcome.value == 1.0


def test_coverage_counts_each_occurrence() -> None:
    # Half of the paper is gone, though every word it used is still somewhere in the book.
    found = source(source_text("repeated words"), source_text("repeated words", page=2))

    outcome = word_coverage(document(), found, ["repeated words"], CONFIG)

    assert outcome.value == 0.5
    assert messages(outcome) == ["2 of 4 words didn't reach the book"]


def test_a_lost_paragraph_is_found_on_its_page_though_its_words_are_elsewhere() -> None:
    found = source(
        source_text("words spoken before", page=1),
        source_text("spoken words before", page=2),
        source_text("before words spoken", page=3),
    )

    outcome = word_coverage(document(), found, ["words spoken before"], CONFIG)

    assert [item.page for item in outcome.findings] == [None, 2, 3]
    assert "3 words here" in outcome.findings[1].message


def test_coverage_just_under_the_threshold_fires() -> None:
    limit = CONFIG.coverage_threshold
    total = 1000
    kept = int(limit * total) - 1
    words = [f"lostword{_letters(index)}" for index in range(total)]
    found = source(source_text(" ".join(words)))

    outcome = word_coverage(document(), found, [" ".join(words[:kept])], CONFIG)

    assert outcome.value == kept / total
    assert outcome.findings


def _letters(index: int) -> str:
    return "".join(chr(97 + (index // 26**power) % 26) for power in range(3))


def test_coverage_at_the_threshold_passes() -> None:
    words = [f"lostword{_letters(index)}" for index in range(1000)]
    found = source(source_text(" ".join(words)))
    kept = round(CONFIG.coverage_threshold * 1000)

    assert not word_coverage(document(), found, [" ".join(words[:kept])], CONFIG).findings


def test_only_the_worst_pages_are_listed() -> None:
    texts = [source_text("absent", page=page) for page in range(1, CONFIG.worst_pages + 3)]

    outcome = word_coverage(document(), source(*texts), [], CONFIG)

    assert len([item for item in outcome.findings if item.page]) == CONFIG.worst_pages


def test_a_source_with_no_words_is_covered() -> None:
    assert word_coverage(document(), source(), [], CONFIG).value == 1.0


def test_words_inside_an_equation_image_are_not_expected() -> None:
    doc = document(equation("1"))
    inside = source_text("formula", page=2, bbox=(20.0, 20.0, 40.0, 30.0))
    outside = source_text("sentence", page=2, bbox=(200.0, 200.0, 240.0, 210.0))

    assert [t.text for t in readable_texts(doc, source(inside, outside))] == ["sentence"]


def test_chart_labels_are_not_expected_but_captions_are() -> None:
    doc = document(figure("1"))
    label = source_text("Accuracy", page=2, bbox=(20.0, 20.0, 40.0, 30.0))
    text = source_text("FIGURE 1 Results", page=2, bbox=(20.0, 80.0, 90.0, 90.0))
    own = replace(caption("figure", "1"), bbox=(15.0, 75.0, 95.0, 95.0))

    assert [t.text for t in readable_texts(doc, source(label, text, captions=(own,)))] == [
        "FIGURE 1 Results"
    ]


# The book's files


PAGE = (
    b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Not body</title></head><body>'
    b"<p>one<b>two</b></p><p>three</p><img alt='hidden' src='a.png'/></body></html>"
)


def epub_file(path: Path, *, page: bytes = PAGE, spine: str = "page") -> Path:
    opf = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><manifest>'
        '<item id="page" href="page.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="gone" href="gone.xhtml" media-type="application/xhtml+xml"/>'
        f'</manifest><spine><itemref idref="{spine}"/></spine></package>'
    )
    container = (
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/page.xhtml", page)
    return path


def test_the_book_is_read_in_spine_order_without_tags_or_attributes(tmp_path: Path) -> None:
    book = read_book(epub_file(tmp_path / "b.epub"))

    assert " ".join("".join(reading_text(book)).split()) == "onetwo three"


def test_a_wellformed_book_passes(tmp_path: Path) -> None:
    assert not xhtml_wellformed(read_book(epub_file(tmp_path / "b.epub"))).findings


def test_a_control_character_in_a_chapter_fires_with_the_file(tmp_path: Path) -> None:
    path = epub_file(tmp_path / "b.epub", page=PAGE.replace(b"three", b"th\x0bree"))

    outcome = xhtml_wellformed(read_book(path))

    assert "page.xhtml isn't well-formed" in outcome.findings[0].message
    assert outcome.findings[0].location.file == "page.xhtml"


def test_a_chapter_that_is_in_the_spine_but_not_the_book_fires(tmp_path: Path) -> None:
    outcome = xhtml_wellformed(read_book(epub_file(tmp_path / "b.epub", spine="gone")))

    assert "gone.xhtml is in the spine but not in the book" in messages(outcome)


def test_a_file_that_is_not_an_epub_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "b.epub"
    path.write_bytes(b"not a zip")

    with pytest.raises(BookError):
        read_book(path)


# epubcheck


def test_epubcheck_errors_warnings_and_notes() -> None:
    report = {
        "messages": [
            {
                "ID": "RSC-005",
                "severity": "ERROR",
                "message": "bad",
                "locations": [{"path": "OEBPS/chapter-01.xhtml", "line": 3}],
            },
            {"ID": "OPF-1", "severity": "FATAL", "message": "worse", "locations": []},
            {"ID": "HTM-1", "severity": "WARNING", "message": "meh", "locations": []},
            {"ID": "ACC-1", "severity": "USAGE", "message": "fyi", "locations": []},
        ]
    }

    found = parse_report(report, "OEBPS")

    assert [item.severity for item in found] == ["error", "error", "warn"]
    assert found[0].message == "RSC-005: bad (OEBPS/chapter-01.xhtml:3)"
    assert found[0].location.file == "chapter-01.xhtml"
    assert found[1].location is None


def test_epubcheck_is_skipped_when_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("offprint.qa.epubcheck.shutil.which", lambda _: None)

    outcome = run_epubcheck(tmp_path / "b.epub", timeout=1)

    assert "isn't installed" in outcome.skipped
    assert not outcome.findings


def test_a_book_is_not_failed_for_lacking_epubcheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("offprint.qa.epubcheck.shutil.which", lambda _: None)
    doc = document(Heading(id="h", level=1, runs=(Text("One"),)))

    report = run_gate(doc, epub=render_epub(doc, tmp_path / "b.epub"), evidence=None)

    assert report.check("epubcheck").status == "skip"
    assert report.verdict == "pass"


def test_real_epubcheck_fires_on_a_broken_book(tmp_path: Path) -> None:
    if shutil.which("epubcheck") is None:
        pytest.skip("epubcheck is not on PATH")

    outcome = run_epubcheck(epub_file(tmp_path / "b.epub"), timeout=120, root="OEBPS")

    assert any(item.severity == "error" for item in outcome.findings)
