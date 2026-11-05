"""The JATS adapter on the real fixture: counts, the book, and how it compares with the PDF path."""

import re
import shutil
import socket
import subprocess
import zipfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import pytest

from offprint.adapters.jats import JatsResult, convert_jats
from offprint.adapters.pdf import convert_pdf
from offprint.cleanup import plain_text
from offprint.ir import (
    Block,
    Cite,
    Document,
    Equation,
    Figure,
    Heading,
    ListItem,
    Paragraph,
    Reference,
    Runs,
    Table,
    validate,
)
from offprint.pipeline import convert_to_epub

FIXTURE = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985"
XML = FIXTURE / "paper.xml"

# What the PDF path finds (test_pdf_fixture.py), with the source's own typography.
SECTIONS = [
    "Introduction",
    "Survey methodology",
    "Datasets",
    "Study on machine learning models for detecting Alzheimer's disease",
    "Comparative analysis of machine learning models",
    "Study on deep learning models for detecting Alzheimer's disease",
    "Evaluation metrics",
    "Discussion",
    "Conclusion and future directions",
    "Author contributions",
    "Conflict of interest",
    "Generative AI statement",
    "Publisher's note",
    "Funding",
    "References",
]


@pytest.fixture(scope="module")
def result() -> JatsResult:
    return convert_jats(XML)


@pytest.fixture(scope="module")
def doc(result: JatsResult) -> Document:
    return result.document


def of_type[T](doc: Document, kind: type[T]) -> list[T]:
    return [block for block in doc.blocks if isinstance(block, kind)]


def test_the_fixture_is_valid_and_nothing_went_unmapped(result: JatsResult) -> None:
    assert validate(result.document) == []
    assert result.problems == ()


def test_the_counts_match_the_article(doc: Document) -> None:
    assert len(of_type(doc, Figure)) == 24
    assert len(of_type(doc, Table)) == 20
    assert len(of_type(doc, Equation)) == 18
    assert len(of_type(doc, Reference)) == 109
    assert len(of_type(doc, ListItem)) == 31


def test_the_numbers_run_in_order(doc: Document) -> None:
    assert [figure.number for figure in of_type(doc, Figure)] == [str(n) for n in range(1, 25)]
    assert [table.number for table in of_type(doc, Table)] == [str(n) for n in range(1, 21)]
    assert [item.number for item in of_type(doc, Equation)] == [str(n) for n in range(1, 19)]


def test_the_sections_match_the_pdf_paths(doc: Document) -> None:
    headings = [plain_text(block.runs) for block in of_type(doc, Heading) if block.level == 1]

    assert headings == SECTIONS


def test_every_figure_holds_a_real_image(doc: Document) -> None:
    for figure in of_type(doc, Figure):
        asset = doc.assets[figure.asset]
        assert asset.mime == "image/jpeg"
        assert asset.width and asset.height


def test_every_equation_has_latex_with_balanced_braces(doc: Document) -> None:
    for equation in of_type(doc, Equation):
        assert equation.latex
        unescaped = equation.latex.replace(r"\{", "").replace(r"\}", "")
        assert unescaped.count("{") == unescaped.count("}"), equation.latex


def _cites(runs: Runs) -> Iterable[str]:
    for run in runs:
        if isinstance(run, Cite):
            yield run.target
        elif hasattr(run, "runs"):
            yield from _cites(run.runs)


def test_every_citation_finds_its_reference(doc: Document) -> None:
    keys = {reference.key for reference in of_type(doc, Reference)}
    cited = {
        target
        for block in of_type(doc, Paragraph)
        for target in _cites(block.runs)
        if target.startswith("B")
    }

    assert len(cited) > 50
    assert cited <= keys


def test_the_metadata_matches_the_pdf_paths(doc: Document) -> None:
    pdf = convert_pdf(FIXTURE / "paper.pdf").meta

    assert [author.name for author in doc.meta.authors] == [a.name for a in pdf.authors]
    assert doc.meta.authors[1].corresponding
    assert doc.meta.license == pdf.license
    assert doc.meta.doi == pdf.doi
    assert doc.meta.year == pdf.year


# Comparing the two paths


def _words(text: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def _text(block: Block) -> str:
    match block:
        case Table():
            cells = [cell for row in (block.header, *block.rows) for cell in row]
            return " ".join(plain_text(runs) for runs in (block.caption, *cells))
        case Figure():
            return plain_text(block.caption)
        case Heading() | Paragraph() | ListItem() | Reference():
            return plain_text(block.runs)
    return ""


def _shared(ours: Document, theirs: Document, *kinds: type) -> float:
    """The share of the words in `ours` that also appear in `theirs`, counting repeats."""
    mine = sum((_words(_text(b)) for b in ours.blocks if isinstance(b, kinds)), Counter())
    other = sum((_words(_text(b)) for b in theirs.blocks if isinstance(b, kinds)), Counter())
    return (mine & other).total() / mine.total()


@pytest.mark.parametrize(
    ("kinds", "from_jats", "from_pdf"),
    [
        ((Heading, Paragraph, ListItem), 0.995, 0.985),
        ((Table, Figure), 0.999, 0.999),
        ((Reference,), 0.995, 0.975),
    ],
    ids=["prose", "tables-and-captions", "references"],
)
def test_the_coverage_difference_between_the_two_paths(
    doc: Document,
    kinds: tuple[type, ...],
    from_jats: float,
    from_pdf: float,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A standalone comparison of the IRs, not the QA gate's word coverage against the source.

    It counts lower-cased words, so word order and styling are invisible to it. The floors sit just
    under today's figures, and SOURCE.md explains what makes up the difference.
    """
    pdf = convert_pdf(FIXTURE / "paper.pdf")

    jats_in_pdf = _shared(doc, pdf, *kinds)
    pdf_in_jats = _shared(pdf, doc, *kinds)

    with capsys.disabled():
        print(f"\ncoverage: {jats_in_pdf:.2%} of JATS in PDF, {pdf_in_jats:.2%} of PDF in JATS")
    assert jats_in_pdf >= from_jats
    assert pdf_in_jats >= from_pdf


# The book


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("convert tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr("offprint.sources.resolver.Http", refuse)


@pytest.fixture(scope="module")
def book(chromium: None, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return convert_to_epub(str(XML), tmp_path_factory.mktemp("book")).path


def test_the_book_has_every_part(book: Path) -> None:
    with zipfile.ZipFile(book) as archive:
        text = "".join(
            archive.read(name).decode()
            for name in archive.namelist()
            if re.search(r"(chapter-\d+|front-matter)\.xhtml$", name)
        )
        names = archive.namelist()

    assert len(re.findall(r"<figure\b", text)) == 24
    assert len(re.findall(r"<table\b", text)) == 20
    assert len(re.findall(r'class="equation"', text)) == 18
    assert sum(name.endswith(".jpg") for name in names) == 24
    assert "OEBPS/images/cover.png" in names


def test_the_book_passes_epubcheck(book: Path) -> None:
    epubcheck = shutil.which("epubcheck")
    if epubcheck is None:
        pytest.skip("epubcheck is not on PATH (brew install epubcheck)")
    outcome = subprocess.run([epubcheck, str(book)], capture_output=True, text=True, timeout=120)
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr


@pytest.mark.usefixtures("no_network")
def test_convert_stays_offline(tmp_path: Path) -> None:
    assert convert_to_epub(str(XML), tmp_path, cover=False).path.is_file()


@pytest.mark.usefixtures("chromium")
def test_every_equation_is_typeset_and_the_gate_passes(tmp_path: Path) -> None:
    conversion = convert_to_epub(str(XML), tmp_path, cover=False)

    assert conversion.problems == ()
    assert conversion.report.verdict == "pass"
    assert conversion.report.counts.equations == 18
