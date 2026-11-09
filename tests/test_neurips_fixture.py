"""The single-column NeurIPS fixture, converted with no `--profile` (#35)."""

import shutil
from pathlib import Path

import pytest

from offprint.adapters.pdf import convert_pdf
from offprint.cleanup import plain_text
from offprint.ir import Document, Equation, Figure, Heading, Reference, Table
from offprint.pipeline import convert_to_epub

PDF = Path(__file__).parent / "fixtures" / "neurips-2026-2611.09197" / "paper.pdf"

# What the gate still reports, each tied to work that isn't done. When one of these is fixed the
# test fails, and the entry goes: the fixture should end at `pass`.
OPEN_FINDINGS = {
    # The booktabs tables have few ruled lines, so detection splits and drops rows (#36, #37).
    "table.empty_header",
    "pdf.dropped_text",
    # An arXiv PDF carries no license text, and `convert` makes no network calls.
    "meta.required",
}


@pytest.fixture(scope="module")
def golden(tmp_path_factory: pytest.TempPathFactory):
    outdir = tmp_path_factory.mktemp("neurips")
    return outdir, convert_to_epub(str(PDF), outdir, cover=False)


@pytest.fixture(scope="module")
def doc() -> Document:
    return convert_pdf(PDF)


def test_the_fixture_converts_without_a_profile_flag(golden) -> None:
    _, conversion = golden

    assert conversion.path.exists()


def test_the_report_lists_only_findings_that_are_still_open(golden) -> None:
    report = golden[1].report

    failed = {result.id for result in report.checks if result.status == "fail"}

    assert failed == OPEN_FINDINGS, [f.message for f in report.findings]
    assert report.verdict == "review"


def test_the_fixture_has_the_counts_of_its_source_md(golden) -> None:
    counts = golden[1].report.counts

    assert (counts.pages, counts.figures, counts.tables) == (18, 11, 6)
    assert (counts.equations, counts.sections) == (7, 12)


def test_the_numbered_equations_appear_once_each(doc: Document) -> None:
    # A "(1)" cross-reference in running text once made a paragraph an equation of the same number.
    numbers = [b.number for b in doc.blocks if isinstance(b, Equation) and b.number]

    assert numbers == ["1", "2", "3", "4", "5", "6", "7"]


def test_a_title_over_two_lines_is_whole(doc: Document) -> None:
    assert doc.meta.title == "Safe Reinforcement Learning via Probabilistic Option Shielding"


def test_each_author_has_their_own_affiliation(doc: Document) -> None:
    summary = [(a.name, a.affiliations, a.markers) for a in doc.meta.authors]

    assert summary == [
        ("Gian Luca Ascari", ("Apixa",), ("∗",)),
        ("Isidoro Tamassia", ("KU Leuven",), ()),
        ("Ying Jiao", ("KU Leuven",), ()),
        ("Luc De Raedt", ("KU Leuven, Örebro University",), ()),
        ("Giuseppe Marra", ("KU Leuven",), ()),
    ]


def test_the_venue_and_arxiv_id_come_from_the_page(doc: Document) -> None:
    assert (
        doc.meta.journal
        == "40th Conference on Neural Information Processing Systems (NeurIPS 2026)"
    )
    assert doc.meta.arxiv_id == "2611.09197"


def test_appendix_headings_keep_their_letter_as_the_number(doc: Document) -> None:
    numbers = [(h.level, h.number) for h in doc.blocks if isinstance(h, Heading) and h.number]

    assert (1, "A") in numbers
    assert (2, "B.1") in numbers
    assert (2, "3.2") in numbers


def test_the_reference_list_is_split_into_entries(doc: Document) -> None:
    references = [b for b in doc.blocks if isinstance(b, Reference)]

    assert len(references) == 34
    assert plain_text(references[1].runs).startswith("Eitan Altman. Constrained Markov")


def test_a_superscript_in_a_caption_stays_in_its_place(doc: Document) -> None:
    tables = [b for b in doc.blocks if isinstance(b, Table) and b.number == "6"]

    assert tables
    assert "per 105 environment steps" in plain_text(tables[0].caption)


def test_every_figure_has_a_caption(doc: Document) -> None:
    figures = [b for b in doc.blocks if isinstance(b, Figure)]

    assert len(figures) == 11
    assert all(plain_text(f.caption) for f in figures)


def test_epubcheck_passes_where_it_is_installed(golden) -> None:
    expected = "skip" if shutil.which("epubcheck") is None else "pass"

    assert golden[1].report.check("epubcheck").status == expected
