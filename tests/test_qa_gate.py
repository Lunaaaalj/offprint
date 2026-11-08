"""The gate end to end: the golden fixture, mutations of it, reports and the command line."""

import json
import shutil
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from offprint import pipeline
from offprint.adapters.pdf import PdfResult, convert_pdf, read_evidence
from offprint.cli import app
from offprint.extraction import SourceEvidence
from offprint.ir import (
    Author,
    Document,
    Equation,
    Figure,
    Heading,
    License,
    Meta,
    Paragraph,
    Problem,
    Provenance,
    Table,
    Text,
)
from offprint.pipeline import convert_to_epub
from offprint.qa import (
    CHECKS,
    QA_SCHEMA_VERSION,
    load_config,
    run_gate,
    summary,
    to_data,
    to_markdown,
)
from offprint.render.epub import block_locations, render_epub

PDF = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985" / "paper.pdf"

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OFFPRINT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OFFPRINT_CONFIG_FILE", str(tmp_path / "no-such-config.toml"))


@pytest.fixture(scope="module")
def doc() -> Document:
    return convert_pdf(PDF)


@pytest.fixture(scope="module")
def evidence() -> SourceEvidence:
    return read_evidence(PDF)


def table_number(doc: Document, number: str) -> Table:
    return next(b for b in doc.blocks if isinstance(b, Table) and b.number == number)


def swap(doc: Document, old: object, new: object) -> Document:
    return replace(doc, blocks=tuple(new if block is old else block for block in doc.blocks))


def without(doc: Document, *dropped: object) -> Document:
    ids = {block.id for block in dropped}
    return replace(
        doc,
        blocks=tuple(block for block in doc.blocks if block.id not in ids),
        provenance={key: value for key, value in doc.provenance.items() if key not in ids},
    )


def fired(report) -> set[str]:
    return {finding.check for finding in report.findings}


# Golden test: the fixture and the counts in its SOURCE.md


@pytest.fixture(scope="module")
def golden(tmp_path_factory: pytest.TempPathFactory):
    outdir = tmp_path_factory.mktemp("golden")
    return outdir, convert_to_epub(str(PDF), outdir, cover=False)


def test_the_fixture_passes_the_gate(golden) -> None:
    _, conversion = golden
    report = conversion.report

    assert report.verdict == "pass", [f.message for f in report.findings]
    assert [result.id for result in report.checks if result.status == "fail"] == []


def test_the_fixture_has_the_counts_of_its_source_md(golden) -> None:
    counts = golden[1].report.counts

    assert (counts.pages, counts.figures, counts.tables) == (35, 24, 20)
    assert (counts.equations, counts.sections) == (18, 15)


def test_the_fixture_reaches_the_coverage_threshold(golden) -> None:
    coverage = golden[1].report.check("coverage.words")

    assert coverage.status == "pass"
    assert coverage.value >= coverage.threshold == load_config().coverage_threshold


def test_epubcheck_passes_where_it_is_installed(golden) -> None:
    expected = "skip" if shutil.which("epubcheck") is None else "pass"

    assert golden[1].report.check("epubcheck").status == expected


def test_the_reports_are_written_next_to_the_book(golden) -> None:
    outdir, conversion = golden

    data = json.loads((outdir / "paper.qa.json").read_text())

    assert data["schema_version"] == QA_SCHEMA_VERSION
    assert data["verdict"] == "pass"
    assert data["epub"] == "paper.epub"
    assert conversion.report_path == outdir / "paper.qa.md"
    assert "**Verdict: pass**" in conversion.report_path.read_text()


def test_every_check_is_reported_even_when_nothing_fired(golden) -> None:
    assert [item.id for item in golden[1].report.checks] == [check.id for check in CHECKS]


# Mutations: break the fixture's IR and the right check fires


def test_the_unmodified_fixture_fires_nothing(doc: Document, evidence: SourceEvidence) -> None:
    assert run_gate(doc, evidence=evidence).findings == ()


@pytest.mark.parametrize("number", ["5", "24"])
def test_dropping_a_figure_fires_counts_figures(
    doc: Document, evidence: SourceEvidence, number: str
) -> None:
    figure = next(b for b in doc.blocks if isinstance(b, Figure) and b.number == number)

    report = run_gate(without(doc, figure), evidence=evidence)

    assert "counts.figures" in fired(report)
    assert report.verdict == "review"
    assert any(f.page == doc.provenance[figure.id].page for f in report.findings)


def test_dropping_a_table_fires_counts_tables(doc: Document, evidence: SourceEvidence) -> None:
    report = run_gate(without(doc, table_number(doc, "20")), evidence=evidence)

    assert fired(report) == {"counts.tables"}


def test_dropping_the_last_equation_fires_counts_equations(
    doc: Document, evidence: SourceEvidence
) -> None:
    last = next(b for b in doc.blocks if isinstance(b, Equation) and b.number == "18")

    assert fired(run_gate(without(doc, last), evidence=evidence)) == {"counts.equations"}


def test_renumbering_an_equation_fires_counts_equations(
    doc: Document, evidence: SourceEvidence
) -> None:
    equation = next(b for b in doc.blocks if isinstance(b, Equation) and b.number == "7")

    report = run_gate(swap(doc, equation, replace(equation, number="8")), evidence=evidence)

    assert "counts.equations" in fired(report)


def test_a_phantom_column_fires_table_empty_header(doc: Document, evidence: SourceEvidence) -> None:
    table = table_number(doc, "2")
    phantom = replace(
        table,
        header=(table.header[0], (), *table.header[1:]),
        rows=tuple((row[0], (), *row[1:]) for row in table.rows),
    )

    assert fired(run_gate(swap(doc, table, phantom), evidence=evidence)) == {"table.empty_header"}


def test_a_short_row_fires_table_width(doc: Document, evidence: SourceEvidence) -> None:
    table = table_number(doc, "2")
    short = replace(table, rows=(table.rows[0][:-1], *table.rows[1:]))

    assert fired(run_gate(swap(doc, table, short), evidence=evidence)) == {"table.width"}


def test_text_after_a_year_fires_table_ref_rows(doc: Document, evidence: SourceEvidence) -> None:
    # What `merge_phantom_columns` used to do to Table 6.
    table = table_number(doc, "6")
    broken = (*table.rows[0][0], Text(" and performance metrics."))
    rows = ((broken, *table.rows[0][1:]), *table.rows[1:])

    report = run_gate(swap(doc, table, replace(table, rows=rows)), evidence=evidence)

    assert fired(report) == {"table.ref_rows"}


def test_a_crop_that_grew_fires_figure_foreign_caption(
    doc: Document, evidence: SourceEvidence
) -> None:
    pairs = [
        (figure, other)
        for figure in evidence.captions
        for other in evidence.captions
        if figure.kind == "figure" and figure.page == other.page and figure is not other
    ]
    figure, other = pairs[0]
    block_id = f"figure-{figure.number}"
    grown = replace(doc.provenance[block_id], bbox=(0.0, 0.0, 600.0, 900.0))
    mutated = replace(doc, provenance={**doc.provenance, block_id: grown})

    report = run_gate(mutated, evidence=evidence)

    assert fired(report) == {"figure.foreign_caption"}
    assert f"{other.kind} {other.number}" in report.findings[0].message


def test_dropping_the_license_fires_meta_required(doc: Document, evidence: SourceEvidence) -> None:
    mutated = replace(doc, meta=replace(doc.meta, license=None))

    assert fired(run_gate(mutated, evidence=evidence)) == {"meta.required"}


def test_a_control_character_in_the_ir_is_reported_but_does_not_stop_the_book(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    paragraph = next(b for b in doc.blocks if isinstance(b, Paragraph))
    dirty = replace(paragraph, runs=(Text("bro\x0bken"), *paragraph.runs))
    mutated = swap(doc, paragraph, dirty)

    report = run_gate(mutated, epub=render_epub(mutated, tmp_path / "m.epub"), evidence=evidence)

    assert report.check("epub.invalid_xml_chars").status == "warn"
    assert report.check("xhtml.wellformed").status == "pass"
    assert report.verdict == "pass"


def test_a_control_character_in_the_file_fires_xhtml_wellformed(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    # The renderer's last line of defence is gone: the prototype lost a chapter this way.
    good = render_epub(doc, tmp_path / "good.epub")
    bad = tmp_path / "bad.epub"
    with zipfile.ZipFile(good.path) as source, zipfile.ZipFile(bad, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith("chapter-03.xhtml"):
                data = data.replace(b"<p>", b"<p>\x0b", 1)
            target.writestr(name, data)

    report = run_gate(doc, epub=replace(good, path=bad), evidence=evidence)

    finding = next(f for f in report.findings if f.check == "xhtml.wellformed")
    assert finding.location.file == "chapter-03.xhtml"
    assert report.verdict == "review"


def test_losing_a_page_of_text_fires_coverage_words(
    doc: Document, evidence: SourceEvidence, tmp_path: Path
) -> None:
    gone = [
        block
        for block in doc.blocks
        if isinstance(block, Paragraph) and doc.provenance[block.id].page == 12
    ]
    mutated = without(doc, *gone)

    report = run_gate(mutated, epub=render_epub(mutated, tmp_path / "m.epub"), evidence=evidence)

    coverage = report.check("coverage.words")
    assert coverage.status == "fail"
    assert coverage.value < coverage.threshold
    overall, worst, *_ = [f for f in report.findings if f.check == "coverage.words"]
    assert "words didn't reach the book" in overall.message
    assert worst.page == 12
    assert report.verdict == "review"


# Where findings point


def test_a_finding_on_a_block_has_its_source_place_and_book_place(
    doc: Document, evidence: SourceEvidence
) -> None:
    table = table_number(doc, "2")
    phantom = replace(table, header=(*table.header[:-1], ()))

    report = run_gate(swap(doc, table, phantom), evidence=evidence)

    finding = report.findings[0]
    assert finding.page == doc.provenance[table.id].page
    assert finding.bbox == doc.provenance[table.id].bbox
    assert finding.location == block_locations(doc)[table.id]
    assert finding.location.fragment is not None


def test_a_finding_with_only_a_page_points_to_that_page_in_the_book(
    doc: Document, evidence: SourceEvidence
) -> None:
    figure = next(b for b in doc.blocks if isinstance(b, Figure) and b.number == "5")

    report = run_gate(without(doc, figure), evidence=evidence)

    finding = next(f for f in report.findings if "shows figure 5" in f.message)
    assert finding.location is not None


def test_block_locations_match_the_anchors_in_the_book(doc: Document, tmp_path: Path) -> None:
    result = render_epub(doc, tmp_path / "b.epub")

    with zipfile.ZipFile(result.path) as book:
        for block in doc.blocks:
            if isinstance(block, Table):
                where = block_locations(doc)[block.id]
                assert f'id="{where.fragment}"' in book.read(f"OEBPS/{where.file}").decode()


# Without some of the inputs


def tiny(**changes: object) -> Document:
    heading = Heading(id="h", level=1, runs=(Text("One"),))
    meta = Meta(title="T", authors=(Author(name="A"),), license=License(spdx="CC-BY-4.0"))
    return Document(
        meta=replace(meta, **changes),
        blocks=(heading,),
        provenance={"h": Provenance(adapter="test", page=1)},
    )


def test_a_source_without_evidence_skips_what_needs_it_and_still_passes(tmp_path: Path) -> None:
    doc = tiny()

    report = run_gate(doc, epub=render_epub(doc, tmp_path / "t.epub"))

    assert report.verdict == "pass"
    assert report.check("coverage.words").status == "skip"
    assert report.check("figure.foreign_caption").status == "skip"
    assert report.check("counts.figures").status == "pass"


def test_a_book_that_cannot_be_read_fails(tmp_path: Path) -> None:
    doc = tiny()
    result = render_epub(doc, tmp_path / "t.epub")
    result.path.write_bytes(b"not a zip")

    report = run_gate(doc, epub=result)

    assert report.check("xhtml.wellformed").status == "fail"
    assert report.verdict == "review"


def test_an_invalid_document_is_reported_under_the_code_validate_gave() -> None:
    doc = tiny()
    doc = replace(doc, blocks=(doc.blocks[0], replace(doc.blocks[0])))

    report = run_gate(doc)

    assert report.check("block.duplicate_id").status == "fail"


# Reports


def failed_report(doc: Document, evidence: SourceEvidence):
    table = table_number(doc, "2")
    return run_gate(
        swap(doc, table, replace(table, header=(*table.header[:-1], ()))), evidence=evidence
    )


def test_the_json_has_the_documented_shape(doc: Document, evidence: SourceEvidence) -> None:
    data = to_data(failed_report(doc, evidence))

    assert list(data) == [
        "schema_version",
        "verdict",
        "score",
        "title",
        "epub",
        "counts",
        "totals",
        "checks",
        "findings",
    ]
    assert data["verdict"] == "review"
    assert data["totals"]["fail"] == 1
    assert sum(data["totals"].values()) == len(data["checks"]) == len(CHECKS)
    assert set(data["checks"][0]) == {
        "id",
        "severity",
        "status",
        "findings",
        "value",
        "threshold",
        "reason",
    }
    finding = data["findings"][0]
    assert set(finding) == {
        "check",
        "severity",
        "message",
        "hint",
        "block_id",
        "page",
        "bbox",
        "location",
    }
    assert set(finding["location"]) == {"file", "fragment"}
    json.dumps(data)


def test_a_failing_report_scores_lower(doc: Document, evidence: SourceEvidence) -> None:
    assert run_gate(doc, evidence=evidence).score > failed_report(doc, evidence).score


def test_a_warning_lowers_the_score_but_not_the_verdict(tmp_path: Path) -> None:
    clean = tiny()
    book = render_epub(clean, tmp_path / "t.epub")
    warning = replace(book, problems=(Problem("epub.link_dropped", "a link went away"),))

    assert 0.5 < run_gate(clean, epub=warning).score < run_gate(clean, epub=book).score
    assert run_gate(clean, epub=warning).verdict == "pass"


def test_the_markdown_says_what_failed_where_and_what_to_try(
    doc: Document, evidence: SourceEvidence
) -> None:
    report = failed_report(doc, evidence)

    text = to_markdown(report)

    assert "**Verdict: review**" in text
    assert "## Errors" in text
    assert "### table.empty_header" in text
    assert "phantom column" in text
    assert f"(page {doc.provenance[table_number(doc, '2').id].page}, " in text
    assert "## All checks" in text


def test_the_markdown_lists_what_was_skipped() -> None:
    assert "- coverage.words: no EPUB was written" in to_markdown(run_gate(tiny()))


def test_the_summary_fits_on_a_screen(doc: Document, evidence: SourceEvidence) -> None:
    table = table_number(doc, "11")
    empty = replace(table, header=tuple(() for _ in table.header))
    many = run_gate(without(swap(doc, table, empty), table_number(doc, "2")), evidence=evidence)

    text = summary(many, Path("paper.qa.md"))

    assert text.startswith("QA review:")
    assert text.endswith("Details: paper.qa.md")
    assert "(and 7 more)" in text
    assert len(text.splitlines()) <= 24


# The command line


def test_review_exits_non_zero_but_keeps_the_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "read_pdf", lambda _, **kwargs: PdfResult(tiny(authors=()), ()))

    result = runner.invoke(app, ["convert", str(PDF), "-o", str(tmp_path), "--no-cover"])

    assert result.exit_code == 3
    assert result.stdout.strip() == str(tmp_path / "paper.epub")
    assert "QA review" in result.stderr
    assert "meta.required: the paper has no author" in result.stderr
    assert (tmp_path / "paper.epub").is_file()
    assert (tmp_path / "paper.qa.json").is_file()


def test_text_the_pdf_adapter_dropped_sends_the_book_to_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = Problem(
        "pdf.dropped_text", "page 4: text touching a figure is left out: 'x'", None, 4
    )
    monkeypatch.setattr(pipeline, "read_pdf", lambda _, **kwargs: PdfResult(tiny(), (problem,)))

    result = runner.invoke(app, ["convert", str(PDF), "-o", str(tmp_path), "--no-cover"])

    assert result.exit_code == 3
    assert "pdf.dropped_text" in result.stderr
    report = json.loads((tmp_path / "paper.qa.json").read_text())
    assert [f["page"] for f in report["findings"] if f["check"] == "pdf.dropped_text"] == [4]


def test_allow_review_overrides_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "read_pdf", lambda _, **kwargs: PdfResult(tiny(authors=()), ()))

    args = ["convert", str(PDF), "-o", str(tmp_path), "--no-cover", "--allow-review"]
    result = runner.invoke(app, args)

    assert result.exit_code == 0
    assert "QA review" in result.stderr


def test_a_pass_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "read_pdf", lambda _, **kwargs: PdfResult(tiny(), ()))
    monkeypatch.setattr(pipeline, "_read_evidence", lambda _, _profile: None)

    result = runner.invoke(app, ["convert", str(PDF), "-o", str(tmp_path), "--no-cover"])

    assert result.exit_code == 0, result.output
    assert "QA pass" in result.stderr
