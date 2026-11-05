"""The PDF adapter on the real fixture: counts, caption text and the failures it taught us."""

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from typer.testing import CliRunner

from offprint.adapters.pdf import convert_pdf
from offprint.cleanup import plain_text
from offprint.cli import app
from offprint.ir import (
    Document,
    Equation,
    Figure,
    Heading,
    ListItem,
    Paragraph,
    Reference,
    Table,
    from_json,
    to_json,
    validate,
)

PDF = Path(__file__).parent / "fixtures" / "frontiers-frai-2026-1748985" / "paper.pdf"

SECTIONS = [
    "Introduction",
    "Survey methodology",
    "Datasets",
    "Study on machine learning models for detecting Alzheimer’s disease",
    "Comparative analysis of machine learning models",
    "Study on deep learning models for detecting Alzheimer’s disease",
    "Evaluation metrics",
    "Discussion",
    "Conclusion and future directions",
    "Author contributions",
    "Funding",
    "Conflict of interest",
    "Generative AI statement",
    "Publisher’s note",
    "References",
]


@pytest.fixture(scope="module")
def doc() -> Iterator[Document]:
    yield convert_pdf(PDF)


def of_type[T](doc: Document, kind: type[T]) -> list[T]:
    return [block for block in doc.blocks if isinstance(block, kind)]


def cells(table: Table) -> list[list[str]]:
    return [[plain_text(cell) for cell in row] for row in table.rows]


def body_text(doc: Document) -> str:
    kinds = Paragraph | ListItem | Reference
    return " ".join(plain_text(b.runs) for b in doc.blocks if isinstance(b, kinds))


def table_number(doc: Document, number: str) -> Table:
    return next(t for t in of_type(doc, Table) if t.number == number)


def test_the_ir_is_valid(doc: Document) -> None:
    assert validate(doc) == []


def test_24_figures_numbered_in_order(doc: Document) -> None:
    assert [f.number for f in of_type(doc, Figure)] == [str(n) for n in range(1, 25)]


def test_20_tables_numbered_in_order(doc: Document) -> None:
    assert [t.number for t in of_type(doc, Table)] == [str(n) for n in range(1, 21)]


def test_18_numbered_equations(doc: Document) -> None:
    equations = of_type(doc, Equation)

    assert [e.number for e in equations] == [str(n) for n in range(1, 19)]


def test_15_top_level_sections(doc: Document) -> None:
    headings = [h for h in of_type(doc, Heading) if h.level == 1]

    assert [plain_text(h.runs) for h in headings] == SECTIONS
    assert [h.number for h in headings[:9]] == [str(n) for n in range(1, 10)]
    assert not any(h.number for h in headings[9:])


def test_every_figure_has_caption_text(doc: Document) -> None:
    captions = {f.number: plain_text(f.caption) for f in of_type(doc, Figure)}

    assert all(captions.values())
    assert captions["1"] == "(A) Axial, (B) coronal, and (C) sagittal, views of brain MRI."
    assert captions["2"] == "Basic steps in Alzheimer’s disease classification."
    assert captions["16"] == "Graphical representation of the performance of ANN."
    assert captions["22"] == "Graphical representation of performance of RNN."
    assert captions["24"] == "Graphical representation of performance of deep learning models."


def test_every_table_has_caption_text(doc: Document) -> None:
    captions = {t.number: plain_text(t.caption) for t in of_type(doc, Table)}

    assert all(captions.values())
    assert not any("Continued" in caption for caption in captions.values())


def test_no_table_row_is_uneven_or_empty(doc: Document) -> None:
    for table in of_type(doc, Table):
        assert table.header, f"Table {table.number} has no header"
        assert all(plain_text(cell) for cell in table.header), f"Table {table.number}"
        assert all(any(row) for row in cells(table)), f"Table {table.number}"


def test_table_8_lost_its_swallowed_text_column(doc: Document) -> None:
    table = table_number(doc, "8")

    assert len(table.header) == 2
    assert "Thisproposedresearch" not in str(cells(table))


def test_the_text_next_to_table_8_is_still_in_the_body(doc: Document) -> None:
    page = doc.provenance[table_number(doc, "8").id].page

    with pymupdf.open(PDF) as pdf:
        blocks = pdf[page - 1].get_text("blocks", flags=pymupdf.TEXT_IGNORE_ACTUALTEXT)

    longest = max((b for b in blocks if b[2] - b[0] < 260), key=lambda b: len(b[4]))
    words = " ".join(longest[4].split()[:6]).replace("ﬁ", "fi")
    assert words in body_text(doc)


def test_phantom_columns_are_gone(doc: Document) -> None:
    # Tables 11 and 19 had an empty-header column holding part of "Datasets".
    for number in ("11", "19"):
        table = table_number(doc, number)
        assert len(table.header) == 8
        assert plain_text(table.header[3]).startswith("Dataset")


def test_tables_across_pages_keep_all_their_rows(doc: Document) -> None:
    assert len(table_number(doc, "11").rows) == 32
    assert len(table_number(doc, "19").rows) == 53


def test_reference_rows_are_joined(doc: Document) -> None:
    for number in ("11", "19"):
        for row in cells(table_number(doc, number)):
            assert re.search(r"\d{4}[a-z]?\)?$", row[0]), row[0]


def test_two_tables_on_one_page_pair_with_their_own_captions(doc: Document) -> None:
    # On p. 14 two tables start at the same y.
    on_page_14 = [t for t in of_type(doc, Table) if doc.provenance[t.id].page == 14]

    assert len(on_page_14) == 2
    assert len({doc.provenance[t.id].bbox[0] for t in on_page_14}) == 2
    captions = [plain_text(t.caption) for t in on_page_14]
    assert len(set(captions)) == 2


def test_figures_keep_colour_and_equations_are_grayscale(doc: Document) -> None:
    figure = doc.assets[of_type(doc, Figure)[5].asset]
    equation = doc.assets[of_type(doc, Equation)[0].asset]

    assert pymupdf.Pixmap(figure.bytes).n == 3
    assert pymupdf.Pixmap(equation.bytes).n == 1


def test_alt_text_comes_through_for_every_figure(doc: Document) -> None:
    figures = {f.number: f for f in of_type(doc, Figure)}

    assert all(f.alt for f in figures.values())
    assert "decision tree" in figures["7"].alt
    assert "Bar chart" in figures["6"].alt


def test_text_is_clean(doc: Document) -> None:
    text = body_text(doc)

    assert not set(text) & set("ﬁﬂﬀﬃﬄ")
    assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text)
    assert "  " not in text


def test_chart_labels_stay_out_of_the_text(doc: Document) -> None:
    paragraphs = [plain_text(p.runs) for p in of_type(doc, Paragraph)]

    assert "Accuracy" not in paragraphs


def test_a_real_compound_survives_a_line_break(doc: Document) -> None:
    assert "magnetization-prepared" in body_text(doc)
    assert "magnetizationprepared" not in body_text(doc)


def test_the_meta_is_filled_from_the_front_matter(doc: Document) -> None:
    meta = doc.meta

    assert meta.title.startswith("Artificial intelligence techniques")
    assert [author.name for author in meta.authors] == ["Y. Nibila", "M. Sivagami"]
    assert [author.corresponding for author in meta.authors] == [False, True]
    assert meta.journal == "Front. Artif. Intell."
    assert (meta.year, meta.volume, meta.article_id) == (2026, "9", "1748985")
    assert meta.doi == "10.3389/frai.2026.1748985"
    assert meta.license is not None
    assert meta.license.spdx == "CC-BY-4.0"
    assert len(meta.keywords) == 7
    assert plain_text(meta.abstract).startswith("Alzheimer’s disease (AD) is")
    assert meta.source_tier == "pdf"


def test_references_are_listed_with_their_dois(doc: Document) -> None:
    references = of_type(doc, Reference)

    assert len(references) == 109
    assert sum(r.doi is not None for r in references) > 90


def test_provenance_points_at_the_source(doc: Document) -> None:
    figure = of_type(doc, Figure)[0]

    assert doc.provenance[figure.id].adapter == "pdf"
    assert doc.provenance[figure.id].page == 3
    assert doc.provenance[figure.id].bbox is not None


def test_the_ir_round_trips_through_json(doc: Document, tmp_path: Path) -> None:
    assert from_json(to_json(doc, tmp_path), tmp_path) == doc


def test_conversion_is_deterministic(doc: Document) -> None:
    assert convert_pdf(PDF) == doc


def test_emit_ir_writes_the_json_and_assets(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["convert", str(PDF), "--emit-ir", "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    target = tmp_path / "paper.ir.json"
    assert result.stdout.strip() == str(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "ir_version" in data
    restored = from_json(target.read_text(encoding="utf-8"), tmp_path / "paper.assets")
    assert validate(restored) == []
    assert len(of_type(restored, Figure)) == 24


def test_emit_ir_reports_a_missing_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["convert", str(tmp_path / "no.pdf"), "--emit-ir"])

    assert result.exit_code == 1
    assert "no such file" in result.stderr


def test_emit_ir_names_the_closest_profile_for_an_unknown_template(tmp_path: Path) -> None:
    other = tmp_path / "other.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((50, 50), "Not a journal page.")
        pdf.save(other)

    result = CliRunner().invoke(app, ["convert", str(other), "--emit-ir", "-o", str(tmp_path)])

    assert result.exit_code == 1
    assert "closest is 'frontiers'" in result.stderr
